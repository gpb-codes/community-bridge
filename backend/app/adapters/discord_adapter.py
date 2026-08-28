from typing import List, Optional

from app.adapters.base import (
    PlatformAdapter, AdapterCapabilities, Capability, OutboundMessage, SpaceInfo,
)
from app.adapters.discord_bot import get_discord_client, run_discord_bot
from app.config import settings
from app.events.bus import loop_guard_mark, loop_guard_check
from app.logging import get_logger, log_struct

logger = get_logger("discord_adapter")


class DiscordAdapter(PlatformAdapter):
    platform = "discord"

    def __init__(self):
        # Discord officially supports everything needed.
        self.capabilities = AdapterCapabilities(states={
            cap.value: "supported" for cap in Capability
        })
        self.capabilities.states[Capability.RECEIVE_SPACE_EVENTS.value] = "supported"

    async def send_message(self, msg: OutboundMessage) -> str:
        client = get_discord_client()
        return await client.send_to_channel(msg.channel_id, msg.content)

    async def list_spaces(self) -> List[SpaceInfo]:
        client = get_discord_client()
        out = []
        for guild in client.guilds:
            for ch in guild.channels:
                out.append(SpaceInfo(
                    space_id=str(ch.id),
                    name=getattr(ch, "name", str(ch.id)),
                    parent_id=str(ch.category_id) if getattr(ch, "category_id", None) else None,
                ))
        return out

    async def create_space(self, name: str, parent_id: Optional[str] = None,
                           guild_id: Optional[str] = None) -> SpaceInfo:
        client = get_discord_client()
        gid = guild_id or settings.DISCORD_GUILD_ID
        if not gid:
            raise ValueError("DISCORD_GUILD_ID is required to create a channel")
        cid = await client.create_channel(gid, name, parent_id)
        return SpaceInfo(space_id=cid, name=name, parent_id=parent_id)

    def mark_bridge_generated(self, platform_message_id: str) -> None:
        loop_guard_mark("discord", platform_message_id)

    def is_bridge_generated(self, platform_message_id: str) -> bool:
        return loop_guard_check("discord", platform_message_id)


def start_discord():
    run_discord_bot()
