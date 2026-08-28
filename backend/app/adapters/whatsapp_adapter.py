import json
import asyncio
from typing import List, Optional

import httpx
from sqlalchemy.orm import Session

from app.adapters.base import (
    PlatformAdapter, AdapterCapabilities, Capability, OutboundMessage, SpaceInfo,
)
from app.config import settings
from app.database import SessionLocal
from app.models import WhatsAppGroup, Community
from app.services.normalize import normalize_channel_name
from app.logging import get_logger, log_struct

logger = get_logger("whatsapp_adapter")


class WhatsAppAdapter(PlatformAdapter):
    platform = "whatsapp"

    def __init__(self):
        # Groups API (create/delete/list groups) is only available for OBA accounts.
        create_supported = "supported" if settings.WHATSAPP_IS_OBA else "manual"
        self.capabilities = AdapterCapabilities(states={
            Capability.RECEIVE_MESSAGE.value: "supported",   # webhook `messages` with group_id
            Capability.SEND_MESSAGE.value: "supported",      # recipient_type: group
            Capability.CREATE_SPACE.value: create_supported,  # Groups API
            Capability.LIST_SPACES.value: create_supported,   # get active groups
            Capability.RECEIVE_SPACE_EVENTS.value: create_supported,  # group_lifecycle_update webhook
            Capability.MEDIA.value: "supported",
            Capability.THREADS.value: "not_supported",  # WA groups have no threads API
            Capability.UPDATE_SPACE.value: "manual",
            Capability.DELETE_SPACE.value: create_supported,
        })
        self._client = httpx.AsyncClient(timeout=20)

    # ----- helpers -----
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }

    # ----- PlatformAdapter impl -----
    async def send_message(self, msg: OutboundMessage) -> str:
        # WhatsApp Cloud API: recipient_type group, to = group_id
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "group",
            "to": msg.channel_id,
            "type": "text",
            "text": {"body": msg.content},
        }
        url = f"{settings.WHATSAPP_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        resp = await self._client.post(url, headers=self._headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        wa_id = data.get("messages", [{}])[0].get("id")
        log_struct(logger, "INFO", "WHATSAPP_MESSAGE_SENT", group_id=msg.channel_id, wa_id=wa_id)
        return wa_id

    async def list_spaces(self) -> List[SpaceInfo]:
        if not self.capabilities.is_supported(Capability.LIST_SPACES):
            return []
        url = f"{settings.WHATSAPP_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/group"
        resp = await self._client.get(url, headers=self._headers())
        resp.raise_for_status()
        groups = resp.json().get("data", [])
        return [SpaceInfo(space_id=g["id"], name=g.get("name", "")) for g in groups]

    async def create_space(self, name: str, parent_id: Optional[str] = None) -> SpaceInfo:
        if not self.capabilities.is_supported(Capability.CREATE_SPACE):
            raise NotImplementedError("WhatsApp group creation requires an Official Business Account (Groups API).")
        url = f"{settings.WHATSAPP_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/groups"
        payload = {"name": name}
        resp = await self._client.post(url, headers=self._headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()
        return SpaceInfo(space_id=data["id"], name=name, extra={"invite_link": data.get("invite_link")})

    async def delete_space(self, space_id: str) -> None:
        if not self.capabilities.is_supported(Capability.DELETE_SPACE):
            raise NotImplementedError("WhatsApp group deletion not available.")
        url = f"{settings.WHATSAPP_API_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/groups/{space_id}"
        resp = await self._client.delete(url, headers=self._headers())
        resp.raise_for_status()

    # ----- loop prevention -----
    def mark_bridge_generated(self, platform_message_id: str) -> None:
        # Stored by the router in Redis; adapter delegates to a shared store.
        from app.events.bus import loop_guard_mark
        loop_guard_mark("whatsapp", platform_message_id)

    def is_bridge_generated(self, platform_message_id: str) -> bool:
        from app.events.bus import loop_guard_check
        return loop_guard_check("whatsapp", platform_message_id)

    # ----- webhook ingestion (called by API route) -----
    async def ingest_webhook(self, change_value: dict, db: Session) -> Optional[dict]:
        """Parse a Meta webhook `messages` change and return a normalized inbound event."""
        messages = change_value.get("messages", [])
        contacts = {c.get("wa_id"): c.get("profile", {}).get("name") for c in change_value.get("contacts", [])}
        out = None
        for m in messages:
            if m.get("type") != "text":
                # media / unsupported — record but forward text placeholder
                body = m.get("text", {}).get("body") if m.get("type") == "text" else f"[{m.get('type')}]"
            else:
                body = m.get("text", {}).get("body", "")
            group_id = m.get("group_id")
            from_id = m.get("from")
            event = {
                "platform": "whatsapp",
                "platform_message_id": m.get("id"),
                "channel_id": group_id,
                "author_id": from_id,
                "author_name": contacts.get(from_id, from_id),
                "content": body,
                "message_type": m.get("type", "text"),
            }
            out = event
        return out

    async def close(self):
        await self._client.aclose()
