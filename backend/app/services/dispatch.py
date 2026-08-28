from app.logging import get_logger, log_struct
from app.services.message_router import route_message
from app.services.auto_discovery import handle_discord_channel_event, handle_whatsapp_group_event
from app.adapters.discord_adapter import DiscordAdapter
from app.adapters.whatsapp_adapter import WhatsAppAdapter
from app.events.bus import loop_guard_mark
from app.adapters.base import OutboundMessage

logger = get_logger("dispatch")
_discord = DiscordAdapter()
_whatsapp = WhatsAppAdapter()


async def handle_event(event: dict) -> None:
    kind = event.get("kind")
    if kind == "discord_message":
        await route_message("discord", event["payload"])
    elif kind == "whatsapp_message":
        await route_message("whatsapp", event["payload"])
    elif kind == "discord_channel_event":
        await handle_discord_channel_event(event.get("action"), event.get("payload", {}))
    elif kind == "whatsapp_group_event":
        await handle_whatsapp_group_event(event.get("payload", {}))
    elif kind == "manual_sync":
        p = event["payload"]
        if p.get("whatsapp_group_id"):
            sent = await _whatsapp.send_message(OutboundMessage(
                channel_id=p["whatsapp_group_id"], content=p["content"], author_name=p["author"]))
            loop_guard_mark("whatsapp", sent)
        if p.get("discord_channel_id"):
            sent = await _discord.send_message(OutboundMessage(
                channel_id=p["discord_channel_id"], content=p["content"], author_name=p["author"]))
            loop_guard_mark("discord", sent)
    else:
        log_struct(logger, "WARNING", "UNKNOWN_EVENT_KIND", kind=kind)
