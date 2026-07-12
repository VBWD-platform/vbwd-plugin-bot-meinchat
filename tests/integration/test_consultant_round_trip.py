"""Modern LLM-bot round-trip: the bot-meinchat-llm ``/consultant`` consumer
answers over the meinchat transport — the successor to the retired chat
``/hello-llm`` proof (see test_meinchat_round_trip). It shows the bot-base seam is
provider-neutral: a command greets and claims the conversation, then free text is
routed to the claimed consultant, which answers via the CORE LLM client.

Runs only when bot-meinchat-llm is installed (it is in the CE free set); an
isolated bot-meinchat CI clone lacks it → skipped. The LLM call is faked; all data
is created through services.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from plugins.bot_meinchat.tests.integration.test_meinchat_round_trip import (
    _build_pipeline,
    _ensure_user_nickname,
    _grant_tokens,
    _latest_bot_reply,
    _provision_bot_user,
    _register_user,
    _start_conversation,
)

CONSULTANT_ANSWER = "The Team Plan is the best fit for a small team."


def _ensure_consultant_enabled(app):
    """Enable bot-meinchat-llm (the /consultant provider) so its command
    registers with the shared bot-command registry. Skip when it isn't
    installed (an isolated bot-meinchat clone)."""
    from vbwd.plugins.base import PluginStatus

    manager = app.plugin_manager
    plugin = manager.get_plugin("bot-meinchat-llm")
    if plugin is None:
        pytest.skip("bot-meinchat-llm (the /consultant consumer) not installed")
    if plugin.status != PluginStatus.ENABLED:
        try:
            manager.enable_plugin("bot-meinchat-llm")
        except ValueError:
            if plugin.status == PluginStatus.INITIALIZED:
                plugin.enable()


def _stub_llm_client(app, monkeypatch, answer_text):
    """Stub the CORE LLM client so the consultant's grounded answer turn returns
    a deterministic structured result instead of a network call."""
    fake_client = MagicMock()
    fake_client.generate.return_value = {
        "reply_text": answer_text,
        "recommendations": [],
        "intent": "browse",
    }
    monkeypatch.setattr(app.container, "llm_client", lambda slug=None: fake_client)


@pytest.mark.integration
def test_consultant_greets_then_answers_free_text_over_meinchat(app, monkeypatch):
    from vbwd.extensions import db

    _ensure_consultant_enabled(app)
    _stub_llm_client(app, monkeypatch, CONSULTANT_ANSWER)

    with app.app_context():
        suffix = uuid.uuid4().hex[:8]
        bot_user_id = _provision_bot_user(
            app, f"consultantbot+{suffix}@bot.local", f"consultant_{suffix}"
        )
        user_id = _register_user(app, "consultantuser@example.com")
        _ensure_user_nickname(app, user_id, f"user{uuid.uuid4().hex[:8]}")
        _grant_tokens(app, user_id, 1000)
        conversation_id = _start_conversation(app, user_id, bot_user_id)
        pipeline = _build_pipeline(app, bot_user_id=bot_user_id)

        # 1) /consultant → the consultant greeting (claims the conversation).
        pipeline.handle_raw_update(
            {
                "conversation_id": str(conversation_id),
                "sender_id": str(user_id),
                "body": "/consultant",
                "protocol": "plain",
            }
        )
        db.session.commit()
        greeting = _latest_bot_reply(app, conversation_id, bot_user_id)
        assert greeting is not None
        assert "consultant" in greeting.body.lower()

        # 2) free text → routed to the claimed consultant → grounded LLM answer.
        pipeline.handle_raw_update(
            {
                "conversation_id": str(conversation_id),
                "sender_id": str(user_id),
                "body": "What plan should I buy for my small team?",
                "protocol": "plain",
            }
        )
        db.session.commit()
        answer = _latest_bot_reply(app, conversation_id, bot_user_id)
        assert answer is not None
        assert CONSULTANT_ANSWER in answer.body
