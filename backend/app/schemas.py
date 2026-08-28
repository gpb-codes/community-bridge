from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Literal
from datetime import datetime


class MappingStatusUpdate(BaseModel):
    status: Literal["active", "degraded", "pending", "disabled", "error"]


class MappingDirectionUpdate(BaseModel):
    direction: Literal["bidirectional", "whatsapp_to_discord", "discord_to_whatsapp"]


class MappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    community_id: str
    whatsapp_group_id: Optional[str] = None
    discord_guild_id: Optional[str] = None
    discord_channel_id: Optional[str] = None
    direction: str
    status: str
    auto_created: bool
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class MappingCreate(BaseModel):
    community_id: str
    whatsapp_group_id: Optional[str] = None
    discord_channel_id: Optional[str] = None
    direction: Literal["bidirectional", "whatsapp_to_discord", "discord_to_whatsapp"] = "bidirectional"


class ManualLinkRequest(BaseModel):
    community_id: str
    discord_channel_id: str
    whatsapp_group_id: Optional[str] = None
    whatsapp_group_name: Optional[str] = None  # used if WA group must be created manually


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    platform: str
    platform_message_id: str
    channel_id: str
    author_name: Optional[str] = None
    content: Optional[str] = None
    message_type: str
    bridge_generated: bool
    meta: Optional[dict] = None
    received_at: Optional[datetime] = None


class ConnectionStatusOut(BaseModel):
    whatsapp: str
    discord: str
    mappings_total: int
    mappings_active: int
    mappings_pending: int
    mappings_error: int
    messages_today: int


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_type: str
    platform: Optional[str] = None
    level: str
    created_at: Optional[datetime] = None


class WhatsAppWebhookVerification(BaseModel):
    hub_mode: Optional[str] = None
    hub_challenge: Optional[str] = None
    hub_verify_token: Optional[str] = None
