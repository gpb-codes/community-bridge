from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    ChannelMapping, Message, MessageMapping, MappingStatus, MappingDirection, PlatformType,
)
from app.adapters.base import OutboundMessage
from app.adapters.discord_adapter import DiscordAdapter
from app.adapters.whatsapp_adapter import WhatsAppAdapter
from app.events.bus import loop_guard_mark, loop_guard_check, dedup_signature, dedup_claim, dedup_release
from app.config import settings
from app.logging import get_logger, log_struct

logger = get_logger("message_router")

_discord = DiscordAdapter()
_whatsapp = WhatsAppAdapter()


def find_mapping(db: Session, platform: str, channel_id: str) -> Optional[ChannelMapping]:
    if platform == "whatsapp":
        return db.query(ChannelMapping).filter(
            ChannelMapping.whatsapp_group_id == channel_id,
            ChannelMapping.status == MappingStatus.ACTIVE,
        ).first()
    else:
        return db.query(ChannelMapping).filter(
            ChannelMapping.discord_channel_id == channel_id,
            ChannelMapping.status == MappingStatus.ACTIVE,
        ).first()


def direction_allows(direction: MappingDirection, source: str) -> bool:
    if direction == MappingDirection.BIDIRECTIONAL:
        return True
    if source == "whatsapp":
        return direction == MappingDirection.WHATSAPP_TO_DISCORD
    return direction == MappingDirection.DISCORD_TO_WHATSAPP


def format_message(source_platform: str, author_name: str, content: str) -> str:
    if source_platform == "whatsapp":
        prefix = settings.WHATSAPP_PREFIX
    else:
        prefix = settings.DISCORD_PREFIX
    return f"{prefix} {author_name}\n{content}"


async def route_message(source_platform: str, payload: dict,
                      discord_adapter=None, whatsapp_adapter=None) -> None:
    # Defense-in-depth: if this inbound message id was produced by the bridge itself,
    # it is an echo and must not be forwarded back. (The Discord Gateway also filters
    # its own bot messages, but this guard makes the loop impossible at the router level.)
    if loop_guard_check(source_platform, payload["platform_message_id"]):
        log_struct(logger, "INFO", "LOOP_PREVENTED", platform=source_platform,
                   mid=payload.get("platform_message_id"))
        return

    sig = dedup_signature(source_platform, payload["platform_message_id"], payload.get("content", ""))
    if not dedup_claim(sig):
        log_struct(logger, "INFO", "MESSAGE_DUPLICATE_SKIPPED", platform=source_platform,
                   mid=payload.get("platform_message_id"))
        return

    da = discord_adapter or _discord
    wa = whatsapp_adapter or _whatsapp

    db = SessionLocal()
    try:
        mapping = find_mapping(db, source_platform, payload["channel_id"])
        if not mapping or not direction_allows(mapping.direction, source_platform):
            log_struct(logger, "INFO", "NO_ACTIVE_MAPPING", platform=source_platform,
                       channel=payload["channel_id"])
            # record inbound message only
            _store_message(db, source_platform, payload, bridge_generated=False)
            db.commit()
            return

        # record inbound
        src_meta = {"reply_to": payload["reply_to"]} if payload.get("reply_to") else None
        src_msg = _store_message(db, source_platform, payload, bridge_generated=False, meta=src_meta)

        if source_platform == "whatsapp":
            dest_platform = "discord"
            dest_channel = mapping.discord_channel_id
            out = OutboundMessage(channel_id=dest_channel, content=format_message("whatsapp", payload["author_name"], payload["content"]), author_name=payload["author_name"])
            sent_id = await da.send_message(out)
            loop_guard_mark("discord", sent_id)
        else:
            dest_platform = "whatsapp"
            dest_channel = mapping.whatsapp_group_id
            if not dest_channel:
                log_struct(logger, "WARNING", "WHATSAPP_GROUP_MISSING", mapping=mapping.id)
                db.commit()
                return
            out = OutboundMessage(channel_id=dest_channel, content=format_message("discord", payload["author_name"], payload["content"]), author_name=payload["author_name"])
            sent_id = await wa.send_message(out)
            loop_guard_mark("whatsapp", sent_id)

        _store_message(db, dest_platform, {
            "platform_message_id": sent_id,
            "channel_id": dest_channel,
            "author_name": None,
            "content": out.content,
            "message_type": "text",
        }, bridge_generated=True)

        mm = MessageMapping(
            correlation_id=sig,
            source_platform=PlatformType(source_platform),
            source_message_id=payload["platform_message_id"],
            destination_platform=PlatformType(dest_platform),
            destination_message_id=sent_id,
            channel_mapping_id=mapping.id,
        )
        db.add(mm)
        db.commit()
        log_struct(logger, "INFO", "MESSAGE_SYNCED", source=source_platform, destination=dest_platform,
                   mapping=mapping.id)
    except Exception as e:
        db.rollback()
        dedup_release(sig)  # allow a retry to resend without being flagged as duplicate
        log_struct(logger, "ERROR", "MESSAGE_SYNC_FAILED", source=source_platform,
                   destination=("discord" if source_platform == "whatsapp" else "whatsapp"),
                   reason=str(e)[:300])
        raise
    finally:
        db.close()


def _store_message(db: Session, platform: str, payload: dict, bridge_generated: bool, meta: dict = None) -> Message:
    m = Message(
        community_id="default",  # resolved from mapping in production
        platform=PlatformType(platform),
        platform_message_id=payload["platform_message_id"],
        channel_id=payload["channel_id"],
        author_id=payload.get("author_id"),
        author_name=payload.get("author_name"),
        content=payload.get("content"),
        message_type=payload.get("message_type", "text"),
        bridge_generated=bridge_generated,
        meta=meta,
    )
    db.add(m)
    db.flush()
    return m
