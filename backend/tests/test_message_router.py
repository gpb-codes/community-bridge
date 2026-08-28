from app.models import Message, MappingStatus, MappingDirection, PlatformType
from app.services import message_router as router_mod
from conftest import make_mapping


def query_inbound(db, platform, pid):
    s = db()
    m = s.query(Message).filter_by(platform=PlatformType(platform),
                                   platform_message_id=pid).first()
    s.close()
    return m


# 1. Discord -> WhatsApp
def test_discord_to_whatsapp(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("discord",
                 {"platform_message_id": "dc-1", "channel_id": "c1", "author_id": "u2",
                  "author_name": "Pedro", "content": "Hola", "message_type": "text", "reply_to": None},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(wa.sends) == 1
    assert len(da.sends) == 0
    assert wa.sends[0].content == "🟣 [Discord] Pedro\nHola"


# 2. WhatsApp -> Discord
def test_whatsapp_to_discord(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "Hola", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 1
    assert len(wa.sends) == 0
    assert da.sends[0].content == "🟢 [WhatsApp] Gabriel\nHola"


# 3. BIDIRECTIONAL allows both directions over the same mapping
def test_bidirectional_allows_both(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active", direction="bidirectional")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "x", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    asyncio.run(router_mod.route_message("discord",
                 {"platform_message_id": "dc-1", "channel_id": "c1", "author_id": "u2",
                  "author_name": "Pedro", "content": "y", "message_type": "text", "reply_to": None},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 1 and len(wa.sends) == 1


# 4. bridge_generated detection
def test_bridge_generated_detection(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    guards["loop"]["discord:dc-echo"] = True  # this id was produced by the bridge
    import asyncio
    asyncio.run(router_mod.route_message("discord",
                 {"platform_message_id": "dc-echo", "channel_id": "c1", "author_id": "u2",
                  "author_name": "Pedro", "content": "echo", "message_type": "text", "reply_to": None},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(wa.sends) == 0  # not forwarded back to WhatsApp


# 5. Never-loop: WhatsApp -> Discord -> STOP
def test_loop_prevention_whatsapp_to_discord_stop(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "Hola", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 1
    echoed_id = da.returns[-1]  # the id the bridge produced on Discord
    # Now that "echo" arrives as an inbound Discord message:
    asyncio.run(router_mod.route_message("discord",
                 {"platform_message_id": echoed_id, "channel_id": "c1", "author_id": "bot",
                  "author_name": "Bridge", "content": "Hola", "message_type": "text", "reply_to": None},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(wa.sends) == 0  # STOP: never goes back to WhatsApp


# 5b. Never-loop: Discord -> WhatsApp -> STOP
def test_loop_prevention_discord_to_whatsapp_stop(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("discord",
                 {"platform_message_id": "dc-1", "channel_id": "c1", "author_id": "u2",
                  "author_name": "Pedro", "content": "Hola", "message_type": "text", "reply_to": None},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(wa.sends) == 1
    echoed_id = wa.returns[-1]  # the id the bridge produced on WhatsApp
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": echoed_id, "channel_id": "g1", "author_id": "bot",
                  "author_name": "Bridge", "content": "Hola", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 0  # STOP


# 6. Deduplication
def test_deduplication(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    p = {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
         "author_name": "Gabriel", "content": "Hola", "message_type": "text"}
    asyncio.run(router_mod.route_message("whatsapp", p, discord_adapter=da, whatsapp_adapter=wa))
    asyncio.run(router_mod.route_message("whatsapp", p, discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 1


# 7. Same message received twice
def test_same_message_twice(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    p = {"platform_message_id": "wa-dup", "channel_id": "g1", "author_id": "u1",
         "author_name": "Gabriel", "content": "repetido", "message_type": "text"}
    for _ in range(2):
        asyncio.run(router_mod.route_message("whatsapp", p, discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 1


# 8. Inexistent mapping
def test_no_mapping(db, guards, adapters):
    da, wa = adapters
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-x", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "x", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 0
    assert query_inbound(db, "whatsapp", "wa-x") is not None
    assert query_inbound(db, "whatsapp", "wa-x").bridge_generated is False


# 9. PENDING mapping
def test_pending_mapping(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "pending")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "x", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 0


# 10. ACTIVE mapping forwards
def test_active_mapping(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "x", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 1


# 11. ERROR mapping
def test_error_mapping(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "error")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "x", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 0


# 12. Retries without duplicates
def test_retry_without_duplicates(db, guards, adapters):
    da, wa = adapters
    wa.fail_times = 1  # first send fails, second succeeds (simulated retry)
    make_mapping(db(), "active")
    import asyncio
    p = {"platform_message_id": "dc-1", "channel_id": "c1", "author_id": "u2",
         "author_name": "Pedro", "content": "Hola", "message_type": "text", "reply_to": None}
    # attempt 1 (fails)
    try:
        asyncio.run(router_mod.route_message("discord", p, discord_adapter=da, whatsapp_adapter=wa))
    except RuntimeError:
        pass
    assert len(wa.sends) == 0
    assert guards["dedup"] == {}  # released, so a retry can resend
    # attempt 2 (succeeds)
    asyncio.run(router_mod.route_message("discord", p, discord_adapter=da, whatsapp_adapter=wa))
    assert len(wa.sends) == 1
    # attempt 3 (genuine duplicate) -> no extra send
    asyncio.run(router_mod.route_message("discord", p, discord_adapter=da, whatsapp_adapter=wa))
    assert len(wa.sends) == 1


# 13. Messages with reply_to preserve reference in metadata
def test_reply_to_metadata(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("discord",
                 {"platform_message_id": "dc-1", "channel_id": "c1", "author_id": "u2",
                  "author_name": "Pedro", "content": "Hola", "message_type": "text", "reply_to": "dc-parent"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(wa.sends) == 1
    inbound = query_inbound(db, "discord", "dc-1")
    assert inbound.meta == {"reply_to": "dc-parent"}


# 14. Discord threads flattened to normal messages towards WhatsApp
def test_thread_flattened(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("discord",
                 {"platform_message_id": "dc-thread", "channel_id": "c1", "author_id": "u2",
                  "author_name": "Pedro", "content": "Respuesta en thread", "message_type": "text",
                  "reply_to": "dc-parent"},
                 discord_adapter=da, whatsapp_adapter=wa))
    # exactly one normal message, no threading mechanism invoked
    assert len(wa.sends) == 1
    assert wa.sends[0].content == "🟣 [Discord] Pedro\nRespuesta en thread"
    assert "THREAD" not in wa.sends[0].content
    assert query_inbound(db, "discord", "dc-thread").meta["reply_to"] == "dc-parent"


# 15. community_id = "default"
def test_community_default(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "x", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    inbound = query_inbound(db, "whatsapp", "wa-1")
    assert inbound.community_id == "default"


# 16. WhatsApp adapter error
def test_whatsapp_adapter_error(db, guards, adapters):
    da, wa = adapters
    wa.fail_times = 1
    make_mapping(db(), "active")
    import asyncio
    p = {"platform_message_id": "dc-1", "channel_id": "c1", "author_id": "u2",
         "author_name": "Pedro", "content": "Hola", "message_type": "text", "reply_to": None}
    raised = False
    try:
        asyncio.run(router_mod.route_message("discord", p, discord_adapter=da, whatsapp_adapter=wa))
    except RuntimeError:
        raised = True
    assert raised
    assert len(wa.sends) == 0
    assert guards["dedup"] == {}  # released for retry


# 17. Discord adapter error
def test_discord_adapter_error(db, guards, adapters):
    da, wa = adapters
    da.fail_times = 1
    make_mapping(db(), "active")
    import asyncio
    p = {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
         "author_name": "Gabriel", "content": "Hola", "message_type": "text"}
    raised = False
    try:
        asyncio.run(router_mod.route_message("whatsapp", p, discord_adapter=da, whatsapp_adapter=wa))
    except RuntimeError:
        raised = True
    assert raised
    assert len(da.sends) == 0
    assert guards["dedup"] == {}


# 18. A successfully processed message generates exactly one message in the destination
def test_single_destination_message(db, guards, adapters):
    da, wa = adapters
    make_mapping(db(), "active")
    import asyncio
    asyncio.run(router_mod.route_message("whatsapp",
                 {"platform_message_id": "wa-1", "channel_id": "g1", "author_id": "u1",
                  "author_name": "Gabriel", "content": "unico", "message_type": "text"},
                 discord_adapter=da, whatsapp_adapter=wa))
    assert len(da.sends) == 1
    # and nothing was sent back to the source platform
    assert len(wa.sends) == 0
