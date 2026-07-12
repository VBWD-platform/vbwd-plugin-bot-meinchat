"""Cross-provider proof: the SAME chat ``/hello-llm`` consumer round-trips over
meinchat with ZERO consumer change and AUTOMATIC identity (no link step).

This is the evidence the bot-base seam is provider-neutral (D6/D10): the chat
consumer that answers over Telegram (chat/tests/integration/test_bot_round_trip)
answers identically when driven through ``MeinchatInboundPipeline`` — only the
transport (an in-process meinchat message instead of a Telegram webhook) and the
identity mechanism (the authenticated meinchat sender vs a redeemed link token)
differ. The LLM call is faked; all data is created through services.
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


def _start_conversation(app, user_a, user_b):
    from vbwd.extensions import db
    from plugins.meinchat.meinchat.repositories.conversation_repository import (
        ConversationRepository,
    )
    from plugins.meinchat.meinchat.services.conversation_service import (
        ConversationService,
    )

    conv = ConversationService(ConversationRepository(db.session)).start_or_get(
        user_a, user_b
    )
    db.session.commit()
    return conv.id


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
    from plugins.meinchat.meinchat.services.message_service import MessageService

    session = db.session
    return MessageService(
        conv_repo=ConversationRepository(session),
        message_repo=MessageRepository(session),
        nickname_repo=NicknameRepository(session),
    )


def _build_pipeline(app, *, bot_user_id):
    """Assemble the bot's MeinchatInboundPipeline exactly as the plugin would,
    but with the chat LLM faked. The provider posts replies as the bot user."""
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


def _latest_bot_reply(app, conversation_id, bot_user_id):
    from vbwd.extensions import db
    from plugins.meinchat.meinchat.repositories.message_repository import (
        MessageRepository,
    )

    rows = MessageRepository(db.session).page(conversation_id, limit=50)
    bot_rows = [row for row in rows if row.sender_id == bot_user_id]
    # page() returns newest-first; the latest bot row is element 0 of that slice.
    return bot_rows[0] if bot_rows else None


@pytest.mark.integration
def test_hello_llm_then_free_text_round_trip_over_meinchat(app, monkeypatch):
    from unittest.mock import MagicMock

    # S97.5 — chat resolves the CORE LLM client (container.llm_client), not the
    # removed plugins.chat.src.llm_adapter. Stub the client so no network runs.
    _fake_llm_client = MagicMock()
    _fake_llm_client.chat.side_effect = lambda messages, **kwargs: FAKE_LLM_ANSWER
    monkeypatch.setattr(app.container, "llm_client", lambda slug=None: _fake_llm_client)
    _enable_chat_bot(app, monkeypatch)

    with app.app_context():
        bot_user_id = _provision_bot_user(app, "meinchatbot@bot.local", "assistant")
        user_id = _register_user(app, "meinchatuser@example.com")
        _ensure_user_nickname(app, user_id, f"user{uuid.uuid4().hex[:8]}")
        _grant_tokens(app, user_id, 1000)
        conversation_id = _start_conversation(app, user_id, bot_user_id)
        starting_balance = app.container.token_service().get_balance(user_id)

        pipeline = _build_pipeline(app, bot_user_id=bot_user_id)

        # 1) /hello-llm → greeting (claims the chat conversation), no debit,
        #    identity automatic (no /start link step performed anywhere).
        pipeline.handle_raw_update(
            {
                "conversation_id": str(conversation_id),
                "sender_id": str(user_id),
                "body": "/hello-llm",
                "protocol": "plain",
            }
        )
        from vbwd.extensions import db

        db.session.commit()
        greeting = _latest_bot_reply(app, conversation_id, bot_user_id)
        assert greeting is not None
        assert "gpt-4o-mini" in greeting.body
        assert greeting.protocol == "plain"

        after_hello = app.container.token_service().get_balance(user_id)
        assert after_hello == starting_balance

        # 2) free text → routed to chat (active owner) → LLM answer, debit.
        pipeline.handle_raw_update(
            {
                "conversation_id": str(conversation_id),
                "sender_id": str(user_id),
                "body": "What is the capital of France?",
                "protocol": "plain",
            }
        )
        db.session.commit()
        answer = _latest_bot_reply(app, conversation_id, bot_user_id)
        assert answer.body == FAKE_LLM_ANSWER

        final_balance = app.container.token_service().get_balance(user_id)
        assert final_balance < after_hello


class _FakeRow:
    """Minimal stand-in for a persisted meinchat ``Message`` row the post-send
    hook receives (the hook only reads conversation_id / sender_id / body)."""

    def __init__(self, *, conversation_id, sender_id, body, protocol="plain"):
        self.conversation_id = conversation_id
        self.sender_id = sender_id
        self.body = body
        self.protocol = protocol


@pytest.mark.integration
def test_user_finds_bot_and_is_answered_in_their_own_conversation(app, monkeypatch):
    """End-to-end participant trigger: a user finds the bot in nickname search,
    opens a conversation with it, and the plugin's post-send hook answers in
    THAT conversation — proving the bot answers anyone who chats with it (no
    single pre-set bot_conversation_id)."""
    from unittest.mock import MagicMock

    # S97.5 — chat resolves the CORE LLM client (container.llm_client), not the
    # removed plugins.chat.src.llm_adapter. Stub the client so no network runs.
    _fake_llm_client = MagicMock()
    _fake_llm_client.chat.side_effect = lambda messages, **kwargs: FAKE_LLM_ANSWER
    monkeypatch.setattr(app.container, "llm_client", lambda slug=None: _fake_llm_client)
    _enable_chat_bot(app, monkeypatch)

    with app.app_context():
        from vbwd.extensions import db
        from plugins.bot_meinchat import BotMeinchatPlugin
        from plugins.meinchat.meinchat.repositories.nickname_repository import (
            NicknameRepository,
        )
        from plugins.meinchat.meinchat.services.nickname_service import (
            NicknameService,
        )

        bot_email = f"hookbot+{uuid.uuid4().hex[:8]}@bot.local"
        bot_nickname = f"hookbot{uuid.uuid4().hex[:6]}"
        bot_user_id = _provision_bot_user(app, bot_email, bot_nickname)

        user_id = _register_user(app, "hookuser@example.com")
        _ensure_user_nickname(app, user_id, f"hookuser{uuid.uuid4().hex[:6]}")
        _grant_tokens(app, user_id, 1000)

        # 1) The user finds the bot in meinchat's nickname search.
        search = NicknameService(NicknameRepository(db.session)).search(
            bot_nickname[:4], caller_user_id=user_id
        )
        assert bot_user_id in {row.user_id for row in search}

        # 2) The user opens a conversation with the bot they found.
        conversation_id = _start_conversation(app, user_id, bot_user_id)

        # Build the plugin and prime its bot-user cache to the provisioned user.
        plugin = BotMeinchatPlugin()
        plugin.initialize({"bot_user_email": bot_email, "bot_nickname": bot_nickname})
        plugin._cached_bot_user_id = bot_user_id
        pipeline = _build_pipeline(app, bot_user_id=bot_user_id)

        from plugins.bot_meinchat.bot_meinchat.services.inbound_hook import (
            MeinchatInboundHook,
        )

        hook = MeinchatInboundHook(
            is_bot_in_conversation=plugin._is_bot_in_conversation,
            resolve_bot_user_id=plugin._resolve_bot_user_id,
            build_pipeline=lambda: pipeline,
        )

        # 3) A message from the user in their conversation with the bot is
        #    ingested and answered in THAT conversation.
        hook.on_sent(
            _FakeRow(
                conversation_id=conversation_id,
                sender_id=user_id,
                body="/hello-llm",
            )
        )
        db.session.commit()
        greeting = _latest_bot_reply(app, conversation_id, bot_user_id)
        assert greeting is not None
        assert "gpt-4o-mini" in greeting.body

        # 4) A conversation the bot is NOT part of is left untouched: a message
        #    between two humans never triggers the bot.
        other_user_id = _register_user(app, "hookother@example.com")
        _ensure_user_nickname(app, other_user_id, f"hookother{uuid.uuid4().hex[:6]}")
        human_conversation_id = _start_conversation(app, user_id, other_user_id)
        hook.on_sent(
            _FakeRow(
                conversation_id=human_conversation_id,
                sender_id=user_id,
                body="this is private",
            )
        )
        db.session.commit()
        assert _latest_bot_reply(app, human_conversation_id, bot_user_id) is None


@pytest.mark.integration
def test_provider_registered_in_bot_base_registry_on_enable(app):
    """On enable the MeinchatProvider appears in bot-base's registry (D10)."""
    with app.app_context():
        container = app.container
        registry = container.messenger_provider_registry()
        assert registry.has("meinchat")
        provider = registry.get("meinchat")
        assert provider.provider_id == "meinchat"
        # Identity is auth-native: no deeplink.
        assert provider.build_link_deeplink("tok") is None
