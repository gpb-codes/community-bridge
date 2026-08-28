import hashlib
import json
from typing import Optional

import redis

from app.config import settings
from app.logging import get_logger, log_struct

logger = get_logger("event_bus")

_r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

QUEUE_KEY = "bridge:events"
LOOP_PREFIX = "bridge:loop:"
DEDUP_PREFIX = "bridge:dedup:"


def enqueue_event(event: dict) -> None:
    """Publish an event to the worker queue (Celery broker)."""
    from app.workers.celery_app import process_event
    process_event.delay(event)
    log_struct(logger, "DEBUG", "EVENT_ENQUEUED", kind=event.get("kind"))


# ----- loop prevention -----
def loop_guard_mark(platform: str, platform_message_id: str) -> None:
    key = f"{LOOP_PREFIX}{platform}:{platform_message_id}"
    _r.set(key, "1", ex=settings.BRIDGE_GENERATED_TTL_SECONDS)


def loop_guard_check(platform: str, platform_message_id: str) -> bool:
    key = f"{LOOP_PREFIX}{platform}:{platform_message_id}"
    return bool(_r.exists(key))


# ----- idempotency / dedup -----
def dedup_signature(source_platform: str, source_message_id: str, content: str) -> str:
    raw = f"{source_platform}:{source_message_id}:{content}"
    return hashlib.sha256(raw.encode()).hexdigest()


def dedup_claim(signature: str, ttl: int = 3600) -> bool:
    """Return True if this signature was NOT seen before (claim it). False => duplicate."""
    key = f"{DEDUP_PREFIX}{signature}"
    return _r.set(key, "1", ex=ttl, nx=True) is not None


def dedup_release(signature: str) -> None:
    """Release a claimed signature (used when sending failed, so a retry can resend)."""
    key = f"{DEDUP_PREFIX}{signature}"
    _r.delete(key)


def ping() -> bool:
    try:
        return _r.ping()
    except Exception:
        return False
