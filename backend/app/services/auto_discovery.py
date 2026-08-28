from typing import Optional

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    DiscordGuild, DiscordChannel, WhatsAppGroup, ChannelMapping, MappingStatus,
    MappingDirection, PlatformType, AuditLog,
)
from app.adapters.discord_adapter import DiscordAdapter
from app.adapters.whatsapp_adapter import WhatsAppAdapter
from app.services.normalize import normalize_channel_name
from app.config import settings
from app.logging import get_logger, log_struct

logger = get_logger("auto_discovery")

_discord = DiscordAdapter()
_whatsapp = WhatsAppAdapter()
COMMUNITY = "default"


def _ensure_guild(db: Session, guild_id: str, name: str) -> DiscordGuild:
    g = db.query(DiscordGuild).filter_by(id=guild_id).first()
    if not g:
        g = DiscordGuild(id=guild_id, community_id=COMMUNITY, name=name)
        db.add(g)
        db.flush()
    return g


def find_whatsapp_group_by_name(db: Session, normalized: str) -> Optional[WhatsAppGroup]:
    return db.query(WhatsAppGroup).filter_by(normalized_name=normalized, community_id=COMMUNITY).first()


def find_discord_channel_by_name(db: Session, normalized: str) -> Optional[DiscordChannel]:
    return db.query(DiscordChannel).filter_by(normalized_name=normalized, community_id=COMMUNITY).first()


def create_mapping(db: Session, wa_group: Optional[WhatsAppGroup],
                   discord_channel: Optional[DiscordChannel], auto_created: bool,
                   status: MappingStatus = MappingStatus.ACTIVE) -> ChannelMapping:
    m = ChannelMapping(
        community_id=COMMUNITY,
        whatsapp_group_id=wa_group.id if wa_group else None,
        discord_guild_id=discord_channel.guild_id if discord_channel else None,
        discord_channel_id=discord_channel.id if discord_channel else None,
        direction=MappingDirection.BIDIRECTIONAL,
        status=status,
        auto_created=auto_created,
        created_by="system",
    )
    db.add(m)
    db.flush()
    db.add(AuditLog(action="mapping_created", entity_type="channel_mapping", entity_id=m.id,
                    detail={"auto_created": auto_created, "status": status.value}))
    return m


async def discover_discord_now(guild) -> None:
    """Initial reconciliation of all Discord channels into DB + mapping attempts."""
    db = SessionLocal()
    try:
        _ensure_guild(db, str(guild.id), guild.name)
        for ch in guild.channels:
            name = getattr(ch, "name", None)
            if not name:
                continue
            normalized = normalize_channel_name(name)
            row = db.query(DiscordChannel).filter_by(id=str(ch.id)).first()
            if not row:
                row = DiscordChannel(
                    id=str(ch.id), guild_id=str(guild.id), community_id=COMMUNITY,
                    name=name, normalized_name=normalized,
                    category_id=str(ch.category_id) if getattr(ch, "category_id", None) else None,
                    channel_type=int(getattr(ch, "type", 0)),
                )
                db.add(row)
                db.flush()
            await try_map_discord_channel(db, row)
        db.commit()
        log_struct(logger, "INFO", "DISCORD_DISCOVERY_DONE", guild=guild.id)
    finally:
        db.close()


async def try_map_discord_channel(db: Session, channel: DiscordChannel) -> None:
    existing = db.query(ChannelMapping).filter_by(discord_channel_id=channel.id).first()
    if existing:
        return
    from app.adapters.base import Capability
    wa = find_whatsapp_group_by_name(db, channel.normalized_name) if channel.normalized_name else None
    if wa:
        create_mapping(db, wa, channel, auto_created=True)
        log_struct(logger, "INFO", "MAPPING_AUTO_CREATED", discord=channel.id, whatsapp=wa.id)
        return
    if _whatsapp.capabilities.is_supported(Capability.CREATE_SPACE):
        try:
            space = await _whatsapp.create_space(channel.name, channel.parent_id)
            wa = WhatsAppGroup(
                id=space.space_id, community_id=COMMUNITY, name=channel.name,
                normalized_name=channel.normalized_name, invite_link=space.extra.get("invite_link"),
            )
            db.add(wa)
            db.flush()
            create_mapping(db, wa, channel, auto_created=True)
            log_struct(logger, "INFO", "WHATSAPP_GROUP_AUTO_CREATED", group=space.space_id)
            return
        except Exception as e:
            log_struct(logger, "WARNING", "WHATSAPP_GROUP_CREATE_FAILED", reason=str(e)[:200])
    create_mapping(db, None, channel, auto_created=False, status=MappingStatus.PENDING)
    log_struct(logger, "INFO", "MAPPING_PENDING_MANUAL", discord=channel.id,
               detail="WhatsApp group requires manual creation")


async def handle_discord_channel_event(action: str, payload: dict) -> None:
    db = SessionLocal()
    try:
        guild_id = payload.get("guild_id")
        channel_id = payload.get("channel_id")
        if action == "channel_create":
            if guild_id:
                _ensure_guild(db, guild_id, "unknown")
            normalized = normalize_channel_name(payload.get("name", ""))
            row = db.query(DiscordChannel).filter_by(id=channel_id).first()
            if not row:
                row = DiscordChannel(id=channel_id, guild_id=guild_id, community_id=COMMUNITY,
                                     name=payload.get("name"), normalized_name=normalized,
                                     category_id=payload.get("parent_id"),
                                     channel_type=payload.get("channel_type", 0))
                db.add(row)
                db.flush()
            await try_map_discord_channel(db, row)
        elif action in ("channel_update", "thread_create"):
            row = db.query(DiscordChannel).filter_by(id=channel_id).first()
            if row and payload.get("name"):
                row.name = payload["name"]
                row.normalized_name = normalize_channel_name(payload["name"])
                if payload.get("parent_id"):
                    row.category_id = payload["parent_id"]
        elif action == "channel_delete":
            row = db.query(DiscordChannel).filter_by(id=channel_id).first()
            if row:
                m = db.query(ChannelMapping).filter_by(discord_channel_id=channel_id).first()
                if m:
                    m.status = MappingStatus.DISABLED
                    db.add(AuditLog(action="mapping_disabled_channel_deleted",
                                    entity_type="channel_mapping", entity_id=m.id))
        db.commit()
    finally:
        db.close()


async def handle_whatsapp_group_event(payload: dict) -> None:
    """Called from Meta webhook group_lifecycle_update."""
    db = SessionLocal()
    try:
        from app.adapters.base import Capability
        group_id = payload.get("group_id")
        name = payload.get("name") or payload.get("group_name") or "whatsapp-group"
        normalized = normalize_channel_name(name)
        wa = db.query(WhatsAppGroup).filter_by(id=group_id).first()
        if not wa:
            wa = WhatsAppGroup(id=group_id, community_id=COMMUNITY, name=name, normalized_name=normalized)
            db.add(wa)
            db.flush()
        existing = db.query(ChannelMapping).filter_by(whatsapp_group_id=group_id).first()
        if not existing:
            dc = find_discord_channel_by_name(db, normalized)
            if dc:
                create_mapping(db, wa, dc, auto_created=True)
            elif _discord.capabilities.is_supported(Capability.CREATE_SPACE):
                cid = await _discord.create_space(normalized, guild_id=settings.DISCORD_GUILD_ID)
                dc = DiscordChannel(id=cid, guild_id=settings.DISCORD_GUILD_ID, community_id=COMMUNITY,
                                    name=normalized, normalized_name=normalized)
                db.add(dc)
                db.flush()
                create_mapping(db, wa, dc, auto_created=True)
            else:
                create_mapping(db, wa, None, auto_created=False, status=MappingStatus.PENDING)
        db.commit()
        log_struct(logger, "INFO", "WHATSAPP_GROUP_DISCOVERED", group=group_id)
    finally:
        db.close()
