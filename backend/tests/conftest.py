import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

import pytest

from app.database import Base
from app.services import message_router as router_mod
from app.adapters.base import AdapterCapabilities, OutboundMessage


class FakeAdapter:
    """In-memory adapter standing in for Discord/WhatsApp. No network / real account."""
    def __init__(self, name: str, fail_times: int = 0):
        self.name = name
        self.fail_times = fail_times
        self.sends = []          # OutboundMessage objects actually sent
        self.returns = []        # ids returned for each send
        self.capabilities = AdapterCapabilities()

    async def send_message(self, msg: OutboundMessage) -> str:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError(f"{self.name} adapter unavailable")
        mid = f"FAKE-{self.name}-{len(self.sends) + 1}"
        self.sends.append(msg)
        self.returns.append(mid)
        return mid


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with patch.object(router_mod, "SessionLocal", SessionLocal):
        yield SessionLocal


@pytest.fixture
def guards():
    """In-memory stand-ins for the Redis loop-guard + dedup functions."""
    loop = {}
    dedup = {}

    def mark(platform, mid):
        loop[f"{platform}:{mid}"] = True

    def check(platform, mid):
        return loop.get(f"{platform}:{mid}", False)

    def claim(sig):
        if sig in dedup:
            return False
        dedup[sig] = True
        return True

    def release(sig):
        dedup.pop(sig, None)

    with patch.object(router_mod, "loop_guard_mark", mark), \
         patch.object(router_mod, "loop_guard_check", check), \
         patch.object(router_mod, "dedup_claim", claim), \
         patch.object(router_mod, "dedup_release", release):
        yield {"loop": loop, "dedup": dedup}


@pytest.fixture
def adapters():
    return FakeAdapter("discord"), FakeAdapter("whatsapp")


def run(coro):
    return asyncio.run(coro)


def make_mapping(session, status, direction="bidirectional",
                 wa_group_id="g1", discord_channel_id="c1"):
    from app.models import ChannelMapping, MappingStatus, MappingDirection
    m = ChannelMapping(
        community_id="default",
        whatsapp_group_id=wa_group_id,
        discord_channel_id=discord_channel_id,
        direction=MappingDirection(direction),
        status=MappingStatus(status),
        created_by="system",
    )
    session.add(m)
    session.commit()
    return m


def wa_payload(pid="wa-1", content="Hola", group="g1", author="Gabriel"):
    return {"platform_message_id": pid, "channel_id": group, "author_id": "u1",
            "author_name": author, "content": content, "message_type": "text"}


def dc_payload(pid="dc-1", content="Hola", channel="c1", author="Pedro", reply_to=None):
    return {"platform_message_id": pid, "channel_id": channel, "guild_id": "G",
            "author_id": "u2", "author_name": author, "content": content,
            "message_type": "text", "reply_to": reply_to}
