import asyncio
import threading
from typing import Optional

import discord
from discord import Intents, Message, TextChannel, CategoryChannel, Guild

from app.config import settings
from app.events.bus import enqueue_event, loop_guard_check, loop_guard_mark
from app.logging import get_logger, log_struct
from app.services.normalize import normalize_channel_name

logger = get_logger("discord_bot")


class DiscordClient(discord.Client):
    """Long-lived Gateway client. Receives events, enqueues to Redis queue."""

    def __init__(self):
        intents = Intents.default()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents, max_messages=None)

    async def on_ready(self):
        log_struct(logger, "INFO", "DISCORD_CONNECTED", bot=self.user.name if self.user else "?")
        # initial discovery of existing channels
        from app.services.auto_discovery import discover_discord_now
        for guild in self.guilds:
            await discover_discord_now(guild)

    async def on_message(self, message: Message):
        # Ignore DMs, other bots, and our own/bridge messages
        if not message.guild:
            return
        if message.author.bot:
            return
        if message.webhook_id:
            # Webhook-sent (we use webhooks for some sends) -> treat as bridge-generated
            return
        if loop_guard_check("discord", message.id):
            return
        event = {
            "kind": "discord_message",
            "payload": {
                "platform_message_id": str(message.id),
                "channel_id": str(message.channel.id),
                "guild_id": str(message.guild.id),
                "author_id": str(message.author.id),
                "author_name": message.author.display_name,
                "content": message.content,
                "message_type": "text",
                # Discord replies/threads are flattened when sent to WhatsApp, but the
                # original reference is preserved in metadata.
                "reply_to": str(message.reference.message_id) if message.reference else None,
            },
        }
        await enqueue_event(event)
        log_struct(logger, "INFO", "MESSAGE_RECEIVED", platform="discord",
                   channel=message.channel.id, message=message.id)

    async def on_guild_channel_create(self, channel):
        await self._channel_event("channel_create", channel)

    async def on_guild_channel_update(self, before, after):
        await self._channel_event("channel_update", after)

    async def on_guild_channel_delete(self, channel):
        await self._channel_event("channel_delete", channel)

    async def on_thread_create(self, thread):
        await self._channel_event("thread_create", thread)

    async def _channel_event(self, action: str, channel):
        if isinstance(channel, (TextChannel, CategoryChannel)) or getattr(channel, "type", None) is not None:
            payload = {
                "guild_id": str(channel.guild.id) if channel.guild else None,
                "channel_id": str(channel.id),
                "name": getattr(channel, "name", None),
                "parent_id": str(channel.category_id) if getattr(channel, "category_id", None) else None,
                "channel_type": int(getattr(channel, "type", 0)),
            }
            await enqueue_event({"kind": "discord_channel_event", "action": action, "payload": payload})
            log_struct(logger, "INFO", "DISCORD_CHANNEL_EVENT", action=action, channel=channel.id)

    # ----- outbound -----
    async def send_to_channel(self, channel_id: str, content: str) -> str:
        channel = self.get_channel(int(channel_id))
        if channel is None:
            channel = await self.fetch_channel(int(channel_id))
        msg = await channel.send(content[:2000])
        loop_guard_mark("discord", msg.id)
        return str(msg.id)

    async def create_channel(self, guild_id: str, name: str, parent_id: Optional[str] = None,
                             channel_type: int = 0) -> str:
        guild = self.get_guild(int(guild_id))
        if guild is None:
            guild = await self.fetch_guild(int(guild_id))
        kwargs = {"name": name}
        if parent_id:
            kwargs["category"] = discord.Object(id=int(parent_id))
        chan = await guild.create_text_channel(**kwargs)
        return str(chan.id)


_client: Optional[DiscordClient] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def get_discord_client() -> DiscordClient:
    global _client
    if _client is None:
        _client = DiscordClient()
    return _client


def run_discord_bot():
    """Run the Gateway client in its own thread with its own event loop."""
    global _loop
    if not settings.DISCORD_BOT_TOKEN:
        log_struct(logger, "WARNING", "DISCORD_TOKEN_MISSING", detail="bot will not start")
        return
    client = get_discord_client()

    def _run():
        global _loop
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(client.start(settings.DISCORD_BOT_TOKEN))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    log_struct(logger, "INFO", "DISCORD_BOT_THREAD_STARTED")
