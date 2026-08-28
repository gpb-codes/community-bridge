import hmac
import hashlib
import time
from fastapi import HTTPException, Header, Depends
from typing import Optional

from app.config import settings


def verify_whatsapp_signature(raw_body: bytes, x_hub_signature_256: Optional[str]) -> bool:
    """Meta sends X-Hub-Signature-256 = sha256 HMAC of body with app secret."""
    if not settings.WHATSAPP_APP_SECRET:
        # In local dev without secret configured, allow but warn via caller.
        return True
    if not x_hub_signature_256:
        return False
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, x_hub_signature_256.replace("sha256=", ""))


def verify_discord_interaction(signature: str, timestamp: str, body: bytes, public_key: str) -> bool:
    """ED25519 verification for Discord Interactions (not used for Gateway)."""
    try:
        from nacl.signing import VerifyKey
        from nacl.exceptions import BadSignatureError
    except Exception:
        return False
    try:
        vk = VerifyKey(bytes.fromhex(public_key))
        vk.verify(timestamp.encode() + body, bytes.fromhex(signature))
        return True
    except Exception:
        return False


def verify_admin_api_key(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid admin API key")


def check_replay(ts_header: Optional[str], max_age: int = None) -> bool:
    if max_age is None:
        max_age = settings.WEBHOOK_MAX_AGE_SECONDS
    if not ts_header:
        return True
    try:
        return (time.time() - int(ts_header)) <= max_age
    except ValueError:
        return False
