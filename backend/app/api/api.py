from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Depends, Header, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    ChannelMapping, Message, Event, MappingStatus, MappingDirection, PlatformType,
    PlatformConnection, ConnectionStatus,
)
from app.schemas import (
    MappingOut, MappingCreate, MappingStatusUpdate, MappingDirectionUpdate, ManualLinkRequest,
    ConnectionStatusOut, EventOut, MessageOut,
)
from app.auth import admin_auth
from app.security import verify_whatsapp_signature
from app.events.bus import enqueue_event
from app.services.message_router import route_message
from app.services.normalize import normalize_channel_name
from app.adapters.discord_adapter import DiscordAdapter
from app.adapters.whatsapp_adapter import WhatsAppAdapter
from app.logging import get_logger, log_struct

logger = get_logger("api")
api_router = APIRouter(prefix=settings.API_V1_PREFIX)
_discord = DiscordAdapter()
_whatsapp = WhatsAppAdapter()


@api_router.get("/health")
def health():
    from app.events.bus import ping
    return {"status": "ok", "redis": ping()}


# ---------------- WhatsApp webhook ----------------
@api_router.get("/webhooks/whatsapp")
def whatsapp_verify(mode: str = "", token: str = "", challenge: str = ""):
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return int(challenge) if challenge.isdigit() else challenge
    raise HTTPException(status_code=403, detail="Verification failed")


@api_router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request,
                           x_hub_signature_256: str = Header(default="")):
    raw = await request.body()
    if not verify_whatsapp_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=403, detail="Invalid signature")
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            field = change.get("field")
            if field == "messages" and value.get("messages"):
                event = await _whatsapp.ingest_webhook(value)
                if event:
                    enqueue_event({"kind": "whatsapp_message", "payload": event})
            elif field == "group_lifecycle_update":
                enqueue_event({"kind": "whatsapp_group_event", "payload": value.get("group_lifecycle_update", value)})
    return {"status": "received"}


# ---------------- Dashboard ----------------
@api_router.get("/dashboard", response_model=ConnectionStatusOut, dependencies=[admin_auth])
def dashboard(db: Session = Depends(get_db)):
    wa = db.query(PlatformConnection).filter_by(platform=PlatformType.WHATSAPP).first()
    dc = db.query(PlatformConnection).filter_by(platform=PlatformType.DISCORD).first()
    total = db.query(func.count(ChannelMapping.id)).scalar() or 0
    active = db.query(func.count(ChannelMapping.id)).filter_by(status=MappingStatus.ACTIVE).scalar() or 0
    pending = db.query(func.count(ChannelMapping.id)).filter_by(status=MappingStatus.PENDING).scalar() or 0
    errors = db.query(func.count(ChannelMapping.id)).filter_by(status=MappingStatus.ERROR).scalar() or 0
    today = datetime.now(timezone.utc).date()
    msgs = db.query(func.count(Message.id)).filter(
        func.date(Message.received_at) == today).scalar() or 0
    return ConnectionStatusOut(
        whatsapp=wa.status.value if wa else "disconnected",
        discord=dc.status.value if dc else "disconnected",
        mappings_total=total, mappings_active=active, mappings_pending=pending,
        mappings_error=errors, messages_today=msgs,
    )


# ---------------- Mappings ----------------
@api_router.get("/mappings", response_model=list[MappingOut], dependencies=[admin_auth])
def list_mappings(db: Session = Depends(get_db)):
    return db.query(ChannelMapping).all()


@api_router.post("/mappings", response_model=MappingOut, dependencies=[admin_auth])
def create_mapping(payload: MappingCreate, db: Session = Depends(get_db)):
    m = ChannelMapping(
        community_id=payload.community_id, whatsapp_group_id=payload.whatsapp_group_id,
        discord_channel_id=payload.discord_channel_id, direction=MappingDirection(payload.direction),
        status=MappingStatus.ACTIVE, created_by="admin",
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@api_router.post("/mappings/manual-link", response_model=MappingOut, dependencies=[admin_auth])
async def manual_link(payload: ManualLinkRequest, db: Session = Depends(get_db)):
    """Admin completes a PENDING mapping: links a Discord channel to an existing or
    manually-created WhatsApp group."""
    from app.models import WhatsAppGroup
    wa_id = payload.whatsapp_group_id
    if not wa_id and payload.whatsapp_group_name:
        if _whatsapp.capabilities.is_supported(__import__("app.adapters.base").Capability.CREATE_SPACE):
            space = await _whatsapp.create_space(payload.whatsapp_group_name)
            wa_id = space.space_id
        else:
            # cannot auto-create; require the admin to create the group in WhatsApp first
            raise HTTPException(status_code=400,
                                detail="WhatsApp group creation requires OBA. Create the group in WhatsApp, "
                                       "then call this endpoint with its whatsapp_group_id (visible in inbound webhooks).")
    # ensure the WhatsApp group row exists (so discovery/reconciliation can reason about it)
    if wa_id and not db.query(WhatsAppGroup).filter_by(id=wa_id).first():
        name = payload.whatsapp_group_name or wa_id
        db.add(WhatsAppGroup(id=wa_id, community_id=payload.community_id, name=name,
                             normalized_name=normalize_channel_name(name)))
        db.flush()
    m = ChannelMapping(community_id=payload.community_id, whatsapp_group_id=wa_id,
                       discord_channel_id=payload.discord_channel_id, direction=MappingDirection.BIDIRECTIONAL,
                       status=MappingStatus.ACTIVE, created_by="admin")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@api_router.patch("/mappings/{mapping_id}/status", response_model=MappingOut, dependencies=[admin_auth])
def update_status(mapping_id: str, payload: MappingStatusUpdate, db: Session = Depends(get_db)):
    m = db.query(ChannelMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")
    m.status = MappingStatus(payload.status)
    db.commit()
    db.refresh(m)
    return m


@api_router.patch("/mappings/{mapping_id}/direction", response_model=MappingOut, dependencies=[admin_auth])
def update_direction(mapping_id: str, payload: MappingDirectionUpdate, db: Session = Depends(get_db)):
    m = db.query(ChannelMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")
    m.direction = MappingDirection(payload.direction)
    db.commit()
    db.refresh(m)
    return m


@api_router.delete("/mappings/{mapping_id}", dependencies=[admin_auth])
def delete_mapping(mapping_id: str, db: Session = Depends(get_db)):
    m = db.query(ChannelMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")
    db.delete(m)  # data row only; audit log retained separately if needed
    db.commit()
    return {"deleted": mapping_id}


@api_router.post("/mappings/{mapping_id}/sync-now", dependencies=[admin_auth])
async def sync_now(mapping_id: str, content: str = Query(...), author: str = Query("Admin"), db: Session = Depends(get_db)):
    """Manual one-off sync (admin initiated). Enqueued to the worker, which holds the
    live Discord client connection."""
    m = db.query(ChannelMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Mapping not found")
    enqueue_event({"kind": "manual_sync", "payload": {
        "whatsapp_group_id": m.whatsapp_group_id,
        "discord_channel_id": m.discord_channel_id,
        "content": content, "author": author,
    }})
    return {"enqueued": True}


# ---------------- Messages / Events ----------------
@api_router.get("/messages", response_model=list[MessageOut], dependencies=[admin_auth])
def list_messages(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Message).order_by(Message.received_at.desc()).limit(limit).all()


@api_router.get("/events", response_model=list[EventOut], dependencies=[admin_auth])
def list_events(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Event).order_by(Event.created_at.desc()).limit(limit).all()


@api_router.get("/connections", dependencies=[admin_auth])
def connections(db: Session = Depends(get_db)):
    return db.query(PlatformConnection).all()
