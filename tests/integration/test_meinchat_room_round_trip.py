"""S86.3 D6/D7 — the SAME bot machinery answers inside a ROOM.

This is the room generalisation of ``test_meinchat_round_trip``: a user sends a
message into a room the assistant bot user is a MEMBER of, and the post-send hook
answers IN THAT ROOM (a ``meinchat_message`` row with ``room_id`` set, plain,
S70 ``meta`` preserved). D7 routing falls out per-room: a ``/command`` routes to
its namespace, free text with an active owner routes to that namespace, and free
text with no active owner returns the help menu. A room the bot is NOT a member
of produces no reply, and the bot's own room reply never loops. The LLM call is
faked; all data is created through services.
"""
import uuid

import pytest

from vbwd.models.enums import TokenTransactionType

CHAT_CONFIG = {
    "llm_api_endpoint": "https://api.fake-llm.local/v1/chat/completions",
    "llm_api_key": "sk-fake",
    "llm_model": "gpt-4o-mini",
    # S97.5 — the greeting's {model} now surfaces the LLM-connection slug
    # (config.get("llm_connection_slug") or "default"), not the legacy llm_model.
    "llm_connection_slug": "gpt-4o-mini",
    "counting_mode": "words",
    "words_per_token": 10,
    "mb_per_token": 0.001,
    "tokens_per_token": 100,
    "system_prompt": "You are a helpful assistant.",
    "max_message_length": 4000,
    "max_history_messages": 20,
    "bot_enabled": True,
    "bot_greeting": "Hello, I am {model}. How may I help you today?",
}

FAKE_LLM_ANSWER = "Paris is the capital of France."


def _register_user(app, email: str):
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository

    auth_service = app.container.auth_service()
    unique_email = email.replace("@", f"+{uuid.uuid4().hex[:8]}@")
    result = auth_service.register(email=unique_email, password="MeinBot123@")
    db.session.commit()
    user = UserRepository(db.session).find_by_id(result.user_id)
    return user.id


def _grant_tokens(app, user_id, amount):
    from vbwd.extensions import db

    app.container.token_service().credit_tokens(
        user_id=user_id,
        amount=amount,
        transaction_type=TokenTransactionType.PURCHASE,
        description="integration seed",
    )
    db.session.commit()


def _provision_bot_user(app, email, nickname):
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository
    from plugins.meinchat.meinchat.repositories.nickname_repository import (
        NicknameRepository,
    )
    from plugins.meinchat.meinchat.services.bot_sender_provisioner import (
        BotSenderProvisioner,
    )
    from plugins.meinchat.meinchat.services.nickname_service import NicknameService

    session = db.session
    provisioner = BotSenderProvisioner(
        user_service=app.container.user_service(),
        user_repository=UserRepository(session),
        nickname_service=NicknameService(NicknameRepository(session)),
        session=session,
    )
    bot_user_id = provisioner.ensure_bot_sender(email, nickname)
    db.session.commit()
    return bot_user_id


def _ensure_user_nickname(app, user_id, nickname):
    from vbwd.extensions import db
    from plugins.meinchat.meinchat.repositories.nickname_repository import (
        NicknameRepository,
    )
    from plugins.meinchat.meinchat.services.nickname_service import NicknameService

    NicknameService(NicknameRepository(db.session)).set_nickname(user_id, nickname)
    db.session.commit()


def _create_room(app, *, creator_id, member_ids):
    from vbwd.extensions import db
    from plugins.meinchat.meinchat.repositories.room_member_repository import (
        RoomMemberRepository,
    )
    from plugins.meinchat.meinchat.repositories.room_repository import RoomRepository
    from plugins.meinchat.meinchat.services.room_protocol import RoomProtocolSelector
    from plugins.meinchat.meinchat.services.room_service import RoomService

    def _role_resolver(user_id):
        user = app.container.user_repository().find_by_id(user_id)
        return user.role if user is not None else None

    selector = RoomProtocolSelector(
        server_capabilities_provider=lambda: ["plain"],
        device_has_keys=lambda _user_id: False,
    )
    service = RoomService(
        room_repo=RoomRepository(db.session),
        member_repo=RoomMemberRepository(db.session),
        protocol_selector=selector,
        role_resolver=_role_resolver,
    )
    room = service.create_room(creator_id, member_ids, name="widget room")
    db.session.commit()
    return room.id


def _message_service(app):
    from vbwd.extensions import db
    from plugins.meinchat.meinchat.repositories.conversation_repository import (
        ConversationRepository,
    )
    from plugins.meinchat.meinchat.repositories.message_repository import (
        MessageRepository,
    )
    from plugins.meinchat.meinchat.repositories.nickname_repository import (
        NicknameRepository,
    )
    from plugins.meinchat.meinchat.repositories.room_member_repository import (
        RoomMemberRepository,
    )
    from plugins.meinchat.meinchat.repositories.room_repository import RoomRepository
    from plugins.meinchat.meinchat.services.message_service import MessageService

    session = db.session
    return MessageService(
        conv_repo=ConversationRepository(session),
        message_repo=MessageRepository(session),
        nickname_repo=NicknameRepository(session),
        room_repo=RoomRepository(session),
        member_repo=RoomMemberRepository(session),
    )


def _build_pipeline(app, *, bot_user_id):
    """Assemble the bot's MeinchatInboundPipeline exactly as the plugin would
    (room/member repos supplied so the bot can reply into a room), LLM faked."""
    from vbwd.extensions import db
    from plugins.bot_meinchat.bot_meinchat.services.inbound_pipeline import (
        MeinchatInboundPipeline,
        build_update_dispatcher,
    )
    from plugins.bot_meinchat.bot_meinchat.services.meinchat_message_sender import (
        MeinchatMessageServiceSender,
    )
    from plugins.bot_meinchat.bot_meinchat.services.meinchat_provider import (
        MeinchatProvider,
    )

    sender = MeinchatMessageServiceSender(
        resolve_bot_user_id=lambda: bot_user_id,
        build_message_service=lambda: _message_service(app),
    )
    provider = MeinchatProvider(message_sender=sender)
    dispatcher = build_update_dispatcher(db.session, app.plugin_manager)
    return MeinchatInboundPipeline(provider, dispatcher)


def _room_hook(app, *, bot_user_id, bot_email, bot_nickname):
    """Build the inbound hook with the plugin's REAL room-membership predicate."""
    from plugins.bot_meinchat import BotMeinchatPlugin
    from plugins.bot_meinchat.bot_meinchat.services.inbound_hook import (
        MeinchatInboundHook,
    )

    plugin = BotMeinchatPlugin()
    plugin.initialize({"bot_user_email": bot_email, "bot_nickname": bot_nickname})
    plugin._cached_bot_user_id = bot_user_id
    pipeline = _build_pipeline(app, bot_user_id=bot_user_id)
    return MeinchatInboundHook(
        is_bot_in_conversation=plugin._is_bot_in_conversation,
        is_bot_in_room=plugin._is_bot_in_room,
        resolve_bot_user_id=plugin._resolve_bot_user_id,
        build_pipeline=lambda: pipeline,
    )


def _enable_chat_bot(app, monkeypatch):
    # The meinchat bot reads its config from the "meinchat" namespace
    # (config_store.get_config("meinchat")); the legacy "chat" plugin was
    # retired, so target meinchat here.
    plugin = app.plugin_manager.get_plugin("meinchat")
    for key, value in CHAT_CONFIG.items():
        plugin.set_config(key, value)

    original_get_config = app.config_store.get_config

    def _patched_get_config(plugin_name):
        if plugin_name == "meinchat":
            return dict(CHAT_CONFIG)
        return original_get_config(plugin_name)

    monkeypatch.setattr(app.config_store, "get_config", _patched_get_config)


def _silence_live_registry_bot(app):
    """Make the live bot_meinchat plugin's registry hook inert (blank bot email).

    Each room send fires the SAME registry post-send chain in this
    session-shared integration DB; the live plugin's default bot nickname is
    `assistant`, and provisioning it would bleed into other specs that also claim
    `assistant`. This test drives its OWN hook explicitly, so the live one stays
    inert (DEFAULT_CONFIG: blank email → bridge inert)."""
    plugin = app.plugin_manager.get_plugin("bot-meinchat")
    if plugin is not None:
        plugin.set_config("bot_user_email", "")
        plugin._cached_bot_user_id = None


def _latest_bot_room_reply(app, room_id, bot_user_id):
    from vbwd.extensions import db
    from plugins.meinchat.meinchat.repositories.message_repository import (
        MessageRepository,
    )

    rows = MessageRepository(db.session).page_room(room_id, limit=50)
    bot_rows = [row for row in rows if row.sender_id == bot_user_id]
    return bot_rows[0] if bot_rows else None


def _user_sends_into_room(app, *, hook, room_id, sender_user_id, body):
    """A user posts a real `meinchat_message` room row, then THIS test's hook
    ingests it — the same two steps the production post-send chain performs.

    The user row is persisted via the MessageRepository (test data setup) rather
    than `send_room_text`, on purpose: `send_room_text` fires the REGISTRY hook
    (the live plugin, whose default bot nickname is `assistant`), which would
    provision the default bot in this session-shared integration DB and bleed
    into other specs. That `send_room_text` fires the post-send chain is proved
    by the unit spec `test_send_room_text_invokes_registered_post_send_hooks`;
    here we exercise the hook's ROOM ingestion + the bot's room reply end to end
    against THIS test's bot."""
    from datetime import datetime, timezone

    from vbwd.extensions import db
    from plugins.meinchat.meinchat.models.message import Message
    from plugins.meinchat.meinchat.repositories.message_repository import (
        MessageRepository,
    )

    row = Message()
    row.room_id = room_id
    row.conversation_id = None
    row.sender_id = sender_user_id
    row.sender_nickname = "user"
    row.body = body
    row.protocol = "plain"
    row.sent_at = datetime.now(timezone.utc)
    MessageRepository(db.session).save(row)
    db.session.commit()
    hook.on_sent(row)
    db.session.commit()


@pytest.mark.integration
def test_user_message_in_a_room_is_answered_by_the_bot_in_that_room(app, monkeypatch):
    from unittest.mock import MagicMock

    # S97.5 — chat resolves the CORE LLM client (container.llm_client), not the
    # removed plugins.chat.src.llm_adapter. Stub the client so no network runs.
    _fake_llm_client = MagicMock()
    _fake_llm_client.chat.side_effect = lambda messages, **kwargs: FAKE_LLM_ANSWER
    monkeypatch.setattr(app.container, "llm_client", lambda slug=None: _fake_llm_client)
    _enable_chat_bot(app, monkeypatch)

    with app.app_context():
        _silence_live_registry_bot(app)
        from vbwd.extensions import db

        bot_email = f"roombot+{uuid.uuid4().hex[:8]}@bot.local"
        bot_nickname = f"roombot{uuid.uuid4().hex[:6]}"
        bot_user_id = _provision_bot_user(app, bot_email, bot_nickname)

        user_id = _register_user(app, "roomuser@example.com")
        _ensure_user_nickname(app, user_id, f"roomuser{uuid.uuid4().hex[:6]}")
        _grant_tokens(app, user_id, 1000)

        room_id = _create_room(app, creator_id=user_id, member_ids=[bot_user_id])
        hook = _room_hook(
            app, bot_user_id=bot_user_id, bot_email=bot_email, bot_nickname=bot_nickname
        )

        # 1) A /command in the room routes to its namespace; the bot replies INTO
        #    the room (D7 command routing per-room).
        _user_sends_into_room(
            app, hook=hook, room_id=room_id, sender_user_id=user_id, body="/help"
        )
        db.session.commit()
        help_reply = _latest_bot_room_reply(app, room_id, bot_user_id)
        assert help_reply is not None
        assert help_reply.room_id == room_id
        assert help_reply.conversation_id is None

        # 2) /hello-llm claims the room for the chat namespace (the active owner).
        _user_sends_into_room(
            app, hook=hook, room_id=room_id, sender_user_id=user_id, body="/hello-llm"
        )
        db.session.commit()
        greeting = _latest_bot_room_reply(app, room_id, bot_user_id)
        assert "gpt-4o-mini" in greeting.body
        assert greeting.protocol == "plain"

        # 3) free text now routes to the active owner (chat) → LLM answer.
        _user_sends_into_room(
            app,
            hook=hook,
            room_id=room_id,
            sender_user_id=user_id,
            body="What is the capital of France?",
        )
        db.session.commit()
        answer = _latest_bot_room_reply(app, room_id, bot_user_id)
        assert answer.body == FAKE_LLM_ANSWER
        assert answer.room_id == room_id


@pytest.mark.integration
def test_bot_room_reply_does_not_trigger_a_second_reply_no_loop(app, monkeypatch):
    from unittest.mock import MagicMock

    # S97.5 — chat resolves the CORE LLM client (container.llm_client), not the
    # removed plugins.chat.src.llm_adapter. Stub the client so no network runs.
    _fake_llm_client = MagicMock()
    _fake_llm_client.chat.side_effect = lambda messages, **kwargs: FAKE_LLM_ANSWER
    monkeypatch.setattr(app.container, "llm_client", lambda slug=None: _fake_llm_client)
    _enable_chat_bot(app, monkeypatch)

    with app.app_context():
        _silence_live_registry_bot(app)
        from vbwd.extensions import db

        bot_email = f"loopbot+{uuid.uuid4().hex[:8]}@bot.local"
        bot_nickname = f"loopbot{uuid.uuid4().hex[:6]}"
        bot_user_id = _provision_bot_user(app, bot_email, bot_nickname)
        user_id = _register_user(app, "loopuser@example.com")
        _ensure_user_nickname(app, user_id, f"loopuser{uuid.uuid4().hex[:6]}")
        _grant_tokens(app, user_id, 1000)

        room_id = _create_room(app, creator_id=user_id, member_ids=[bot_user_id])
        hook = _room_hook(
            app, bot_user_id=bot_user_id, bot_email=bot_email, bot_nickname=bot_nickname
        )

        _user_sends_into_room(
            app, hook=hook, room_id=room_id, sender_user_id=user_id, body="/help"
        )
        db.session.commit()
        reply = _latest_bot_room_reply(app, room_id, bot_user_id)
        assert reply is not None

        # The bot's own reply also fired the hook — it must NOT be re-ingested,
        # so no further bot row appears for the same room.
        bot_row_count = len(
            [
                row
                for row in _message_service(app).list_room_messages(
                    room_id, caller_user_id=user_id
                )
                if row.sender_id == bot_user_id
            ]
        )
        assert bot_row_count == 1


@pytest.mark.integration
def test_room_without_a_bot_member_produces_no_bot_reply(app, monkeypatch):
    from unittest.mock import MagicMock

    # S97.5 — chat resolves the CORE LLM client (container.llm_client), not the
    # removed plugins.chat.src.llm_adapter. Stub the client so no network runs.
    _fake_llm_client = MagicMock()
    _fake_llm_client.chat.side_effect = lambda messages, **kwargs: FAKE_LLM_ANSWER
    monkeypatch.setattr(app.container, "llm_client", lambda slug=None: _fake_llm_client)
    _enable_chat_bot(app, monkeypatch)

    with app.app_context():
        _silence_live_registry_bot(app)
        from vbwd.extensions import db

        bot_email = f"absentbot+{uuid.uuid4().hex[:8]}@bot.local"
        bot_nickname = f"absentbot{uuid.uuid4().hex[:6]}"
        bot_user_id = _provision_bot_user(app, bot_email, bot_nickname)

        user_id = _register_user(app, "noreuser@example.com")
        _ensure_user_nickname(app, user_id, f"noreuser{uuid.uuid4().hex[:6]}")
        other_id = _register_user(app, "noreother@example.com")
        _ensure_user_nickname(app, other_id, f"noreother{uuid.uuid4().hex[:6]}")

        # A room of two humans — the bot is NOT a member.
        room_id = _create_room(app, creator_id=user_id, member_ids=[other_id])
        # The hook carries the real predicate, so it must stay inert here.
        hook = _room_hook(
            app, bot_user_id=bot_user_id, bot_email=bot_email, bot_nickname=bot_nickname
        )

        _user_sends_into_room(
            app,
            hook=hook,
            room_id=room_id,
            sender_user_id=user_id,
            body="anyone there?",
        )
        db.session.commit()

        assert _latest_bot_room_reply(app, room_id, bot_user_id) is None
