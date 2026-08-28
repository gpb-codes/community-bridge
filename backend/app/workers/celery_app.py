import asyncio

from celery import Celery

from app.config import settings
from app.logging import get_logger, log_struct

logger = get_logger("celery")

celery_app = Celery(
    "community_bridge",
    broker=settings.celery_broker,
    backend=settings.celery_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_default_queue="bridge",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=4,
)


# The Discord Gateway (long-lived WebSocket) runs inside the worker, because the
# worker is the process that actually sends messages via the Discord client.
from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def _boot_discord(**_):
    from app.adapters.discord_adapter import start_discord
    start_discord()


@celery_app.task(name="process_event", bind=True, max_retries=5)
def process_event(self, event: dict):
    """Worker entrypoint. Uses exponential backoff on failure (no duplication)."""
    from app.services.dispatch import handle_event
    try:
        asyncio.run(handle_event(event))
    except Exception as exc:
        log_struct(logger, "ERROR", "WORKER_PROCESS_FAILED", kind=event.get("kind"), reason=str(exc)[:300])
        # exponential backoff: 2^n * 1s, capped
        raise self.retry(exc=exc, countdown=min(2 ** self.request.retries, 300))
