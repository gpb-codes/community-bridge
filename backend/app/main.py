from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base, SessionLocal
from app.models import Community, Platform, PlatformConnection, ConnectionStatus
from app.logging import get_logger, log_struct
from app.api.api import api_router

logger = get_logger("main")


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if not db.query(Community).filter_by(slug="default").first():
            c = Community(id="default", name="Default Community", slug="default")
            db.add(c)
            for pid, name in [("whatsapp", "WhatsApp"), ("discord", "Discord")]:
                if not db.query(Platform).filter_by(id=pid).first():
                    db.add(Platform(id=pid, name=name, capabilities={}))
                db.add(PlatformConnection(id=f"default-{pid}", community_id="default",
                                          platform=pid, status=ConnectionStatus.PENDING))
        db.commit()
    finally:
        db.close()


async def reconciliation_loop():
    from app.services.reconciliation import MappingReconciliationService
    while True:
        await MappingReconciliationService.reconcile()
        await asyncio_sleep(300)


import asyncio as _asyncio
asyncio_sleep = _asyncio.sleep


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log_struct(logger, "INFO", "STARTUP", project=settings.PROJECT_NAME)
    _asyncio.create_task(reconciliation_loop())
    yield
    log_struct(logger, "INFO", "SHUTDOWN")


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router)
