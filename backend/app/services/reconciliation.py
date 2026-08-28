from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    ChannelMapping, DiscordChannel, WhatsAppGroup, MappingStatus, AuditLog,
)
from app.logging import get_logger, log_struct

logger = get_logger("reconciliation")


class MappingReconciliationService:
    """Detects broken/duplicate/deleted mappings. Never deletes data silently."""

    @staticmethod
    async def reconcile() -> dict:
        db = SessionLocal()
        report = {"broken": 0, "duplicates": 0, "relinked": 0, "disabled": 0}
        try:
            # 1) PENDING mappings: try to auto-complete if counterpart now exists
            pending = db.query(ChannelMapping).filter_by(status=MappingStatus.PENDING).all()
            for m in pending:
                if m.discord_channel_id and not m.whatsapp_group_id:
                    dc = db.query(DiscordChannel).filter_by(id=m.discord_channel_id).first()
                    wa = db.query(WhatsAppGroup).filter_by(
                        normalized_name=dc.normalized_name).first() if dc and dc.normalized_name else None
                    if wa:
                        m.whatsapp_group_id = wa.id
                        m.status = MappingStatus.ACTIVE
                        report["relinked"] += 1
                        db.add(AuditLog(action="mapping_relinked", entity_type="channel_mapping",
                                        entity_id=m.id))
                elif m.whatsapp_group_id and not m.discord_channel_id:
                    wa = db.query(WhatsAppGroup).filter_by(id=m.whatsapp_group_id).first()
                    dc = db.query(DiscordChannel).filter_by(
                        normalized_name=wa.normalized_name).first() if wa and wa.normalized_name else None
                    if dc:
                        m.discord_channel_id = dc.id
                        m.discord_guild_id = dc.guild_id
                        m.status = MappingStatus.ACTIVE
                        report["relinked"] += 1
                        db.add(AuditLog(action="mapping_relinked", entity_type="channel_mapping",
                                        entity_id=m.id))

            # 2) active mappings whose Discord channel no longer exists -> DISABLED
            for m in db.query(ChannelMapping).filter_by(status=MappingStatus.ACTIVE).all():
                if m.discord_channel_id and not db.query(DiscordChannel).filter_by(id=m.discord_channel_id).first():
                    m.status = MappingStatus.DISABLED
                    report["disabled"] += 1
                    db.add(AuditLog(action="mapping_broken_no_channel",
                                    entity_type="channel_mapping", entity_id=m.id))

            # 3) duplicate mappings (same pair) -> keep first, flag rest as ERROR
            seen = set()
            for m in db.query(ChannelMapping).all():
                key = (m.whatsapp_group_id, m.discord_channel_id)
                if key in seen:
                    m.status = MappingStatus.ERROR
                    report["duplicates"] += 1
                    db.add(AuditLog(action="mapping_duplicate", entity_type="channel_mapping",
                                    entity_id=m.id))
                seen.add(key)

            db.commit()
            log_struct(logger, "INFO", "RECONCILIATION_DONE", **report)
            return report
        finally:
            db.close()
