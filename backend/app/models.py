import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, DateTime, Boolean, ForeignKey, Text, Enum, JSON, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class PlatformType(str, enum.Enum):
    WHATSAPP = "whatsapp"
    DISCORD = "discord"


class MappingStatus(str, enum.Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    PENDING = "pending"      # requires manual completion (e.g. WA group not auto-creatable)
    DISABLED = "disabled"
    ERROR = "error"


class MappingDirection(str, enum.Enum):
    BIDIRECTIONAL = "bidirectional"
    WHATSAPP_TO_DISCORD = "whatsapp_to_discord"
    DISCORD_TO_WHATSAPP = "discord_to_whatsapp"


class ConnectionStatus(str, enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    PENDING = "pending"


class CapabilityState(str, enum.Enum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    MANUAL = "manual"


# ---------------------------------------------------------------------------
# Communities (multi-tenant)
# ---------------------------------------------------------------------------
class Community(Base):
    __tablename__ = "communities"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow)

    connections = relationship("PlatformConnection", back_populates="community")
    mappings = relationship("ChannelMapping", back_populates="community")


# ---------------------------------------------------------------------------
# Platforms (catalog)
# ---------------------------------------------------------------------------
class Platform(Base):
    __tablename__ = "platforms"

    id = Column(String, primary_key=True)  # whatsapp / discord
    name = Column(String, nullable=False)
    capabilities = Column(JSON, nullable=True)  # capability -> CapabilityState


# ---------------------------------------------------------------------------
# Platform connections (per community)
# ---------------------------------------------------------------------------
class PlatformConnection(Base):
    __tablename__ = "platform_connections"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    platform = Column(Enum(PlatformType), nullable=False)
    status = Column(Enum(ConnectionStatus), default=ConnectionStatus.PENDING)
    config = Column(JSON, nullable=True)  # encrypted secrets reference
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow)

    community = relationship("Community", back_populates="connections")


# ---------------------------------------------------------------------------
# Users (administrators / bridge operators)
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    email = Column(String, unique=True, nullable=False)
    display_name = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


class PlatformUser(Base):
    __tablename__ = "platform_users"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    platform = Column(Enum(PlatformType), nullable=False)
    platform_user_id = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)

    __table_args__ = (UniqueConstraint("community_id", "platform", "platform_user_id", name="uq_platform_user"),)


# ---------------------------------------------------------------------------
# WhatsApp groups
# ---------------------------------------------------------------------------
class WhatsAppGroup(Base):
    __tablename__ = "whatsapp_groups"

    id = Column(String, primary_key=True)  # group_id from API
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    name = Column(String, nullable=False)  # original name kept in DB
    normalized_name = Column(String, nullable=True)
    wa_business_phone_id = Column(String, nullable=True)
    invite_link = Column(String, nullable=True)
    participant_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow)

    mappings = relationship("ChannelMapping", back_populates="whatsapp_group")


# ---------------------------------------------------------------------------
# Discord guilds + channels
# ---------------------------------------------------------------------------
class DiscordGuild(Base):
    __tablename__ = "discord_guilds"

    id = Column(String, primary_key=True)  # guild snowflake
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    name = Column(String, nullable=False)
    owner_id = Column(String, nullable=True)
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow)

    channels = relationship("DiscordChannel", back_populates="guild")


class DiscordChannel(Base):
    __tablename__ = "discord_channels"

    id = Column(String, primary_key=True)  # channel snowflake
    guild_id = Column(String, ForeignKey("discord_guilds.id"), nullable=False)
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    name = Column(String, nullable=False)
    normalized_name = Column(String, nullable=True)
    category_id = Column(String, nullable=True)  # parent category snowflake
    channel_type = Column(Integer, default=0)  # 0 text, 5 announcement, 11 public thread...
    is_active = Column(Boolean, default=True)
    discovered_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow)

    guild = relationship("DiscordGuild", back_populates="channels")
    mappings = relationship("ChannelMapping", back_populates="discord_channel")


# ---------------------------------------------------------------------------
# Channel mappings (the heart of the bridge)
# ---------------------------------------------------------------------------
class ChannelMapping(Base):
    __tablename__ = "channel_mappings"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    whatsapp_group_id = Column(String, ForeignKey("whatsapp_groups.id"), nullable=True)
    discord_guild_id = Column(String, ForeignKey("discord_guilds.id"), nullable=True)
    discord_channel_id = Column(String, ForeignKey("discord_channels.id"), nullable=True)
    direction = Column(Enum(MappingDirection), default=MappingDirection.BIDIRECTIONAL)
    status = Column(Enum(MappingStatus), default=MappingStatus.PENDING)
    auto_created = Column(Boolean, default=False)
    created_by = Column(String, nullable=True)  # "system" | "admin" | user id
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow, onupdate=utcnow)

    community = relationship("Community", back_populates="mappings")
    whatsapp_group = relationship("WhatsAppGroup", back_populates="mappings")
    discord_channel = relationship("DiscordChannel", back_populates="mappings")

    __table_args__ = (
        UniqueConstraint("whatsapp_group_id", "discord_channel_id", name="uq_mapping_pair"),
    )


# ---------------------------------------------------------------------------
# Messages + message_mappings (loop prevention / correlation)
# ---------------------------------------------------------------------------
class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    platform = Column(Enum(PlatformType), nullable=False)
    platform_message_id = Column(String, nullable=False)
    channel_id = Column(String, nullable=False)  # group_id or channel snowflake
    author_id = Column(String, nullable=True)
    author_name = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    message_type = Column(String, default="text")  # text/image/document/audio/video
    bridge_generated = Column(Boolean, default=False)
    meta = Column(JSON, nullable=True)  # e.g. {"reply_to": "<platform_message_id>"} (threads flattened)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)

    __table_args__ = (
        UniqueConstraint("platform", "platform_message_id", name="uq_message_platform_id"),
    )


class MessageMapping(Base):
    __tablename__ = "message_mappings"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    correlation_id = Column(String, nullable=False, index=True)
    source_platform = Column(Enum(PlatformType), nullable=False)
    source_message_id = Column(String, nullable=False)
    destination_platform = Column(Enum(PlatformType), nullable=False)
    destination_message_id = Column(String, nullable=False)
    channel_mapping_id = Column(String, ForeignKey("channel_mappings.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------
class Media(Base):
    __tablename__ = "media"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    message_id = Column(String, ForeignKey("messages.id"), nullable=False)
    platform = Column(Enum(PlatformType), nullable=False)
    media_type = Column(String, nullable=False)  # image/document/audio/video
    original_url = Column(String, nullable=True)
    local_path = Column(String, nullable=True)  # secure temp storage
    mime_type = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


# ---------------------------------------------------------------------------
# Events (structured audit of bridge events)
# ---------------------------------------------------------------------------
class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    community_id = Column(String, ForeignKey("communities.id"), nullable=True)
    event_type = Column(String, nullable=False)  # MESSAGE_RECEIVED / MAPPING_FOUND / etc
    platform = Column(Enum(PlatformType), nullable=True)
    payload = Column(JSON, nullable=True)
    level = Column(String, default="info")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


# ---------------------------------------------------------------------------
# Sync rules
# ---------------------------------------------------------------------------
class SyncRule(Base):
    __tablename__ = "sync_rules"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    community_id = Column(String, ForeignKey("communities.id"), nullable=False)
    name = Column(String, nullable=False)
    mapping_id = Column(String, ForeignKey("channel_mappings.id"), nullable=True)
    config = Column(JSON, nullable=True)  # filters, prefix overrides, etc
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    actor = Column(String, nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class Error(Base):
    __tablename__ = "errors"

    id = Column(String, primary_key=True, default=lambda: __import__("uuid").uuid4().hex)
    community_id = Column(String, ForeignKey("communities.id"), nullable=True)
    source_platform = Column(Enum(PlatformType), nullable=True)
    destination_platform = Column(Enum(PlatformType), nullable=True)
    error_code = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    trace = Column(Text, nullable=True)
    resolved = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=utcnow)
