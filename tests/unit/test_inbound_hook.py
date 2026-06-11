"""Unit specs for MeinchatInboundHook — the in-process transport (no DB, no net).

The hook is registered as a meinchat ``IPostSendHook``; meinchat fires it after
every send. The hook is the bot's *inbound* edge: it ingests a message ONLY when

  * it lands in a conversation where the configured bot user is a participant AND
  * its sender is not the bot itself (the bot's own replies must not loop).

Everything else (every human↔human conversation the bot is NOT part of, the bot's
own outbound rows) is left untouched — proving the bridge never reads human
chats. The trigger is *participant-based*: any user who finds the bot and opens a
conversation with it gets answered in THAT conversation — there is no single
designated ``bot_conversation_id`` any more.
"""
from uuid import uuid4

from plugins.bot_base.bot_base.types import BotReply
from plugins.bot_meinchat.bot_meinchat.services.inbound_hook import (
    MeinchatInboundHook,
)


class _FakeRow:
    """Minimal stand-in for a meinchat ``Message`` row."""

    def __init__(self, *, conversation_id, sender_id, body, protocol="plain"):
        self.conversation_id = conversation_id
        self.sender_id = sender_id
        self.body = body
        self.protocol = protocol
        self.envelope = None


class _CapturingPipeline:
    """Records the raw payloads handed to the bot pipeline."""

    def __init__(self) -> None:
        self.handled = []

    def handle_raw_update(self, raw: dict) -> BotReply:
        self.handled.append(raw)
        return BotReply(text="ok")


def _hook(*, bot_conversations, bot_user_id, pipeline):
    """Build a hook whose participant test is satisfied for any conversation id
    in ``bot_conversations`` (a set of conversation ids the bot is part of)."""
    bot_conversation_ids = {str(conversation_id) for conversation_id in bot_conversations}
    return MeinchatInboundHook(
        is_bot_in_conversation=lambda conversation_id: (
            str(conversation_id) in bot_conversation_ids
        ),
        resolve_bot_user_id=lambda: bot_user_id,
        build_pipeline=lambda: pipeline,
    )


def test_message_in_a_bot_conversation_from_a_user_is_ingested():
    conversation_id = uuid4()
    bot_user_id = uuid4()
    human_sender = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(
        bot_conversations={conversation_id},
        bot_user_id=bot_user_id,
        pipeline=pipeline,
    )

    hook.on_sent(
        _FakeRow(
            conversation_id=conversation_id,
            sender_id=human_sender,
            body="/hello",
        )
    )

    assert len(pipeline.handled) == 1
    raw = pipeline.handled[0]
    assert raw["conversation_id"] == str(conversation_id)
    assert raw["sender_id"] == str(human_sender)
    assert raw["body"] == "/hello"


def test_any_user_who_opens_a_chat_with_the_bot_is_answered():
    """Two different users each open their OWN conversation with the bot; both
    are ingested (no single pre-set bot conversation)."""
    bot_user_id = uuid4()
    conversation_with_user_a = uuid4()
    conversation_with_user_b = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(
        bot_conversations={conversation_with_user_a, conversation_with_user_b},
        bot_user_id=bot_user_id,
        pipeline=pipeline,
    )

    hook.on_sent(
        _FakeRow(conversation_id=conversation_with_user_a, sender_id=user_a, body="hi")
    )
    hook.on_sent(
        _FakeRow(conversation_id=conversation_with_user_b, sender_id=user_b, body="yo")
    )

    assert [raw["conversation_id"] for raw in pipeline.handled] == [
        str(conversation_with_user_a),
        str(conversation_with_user_b),
    ]


def test_bot_own_reply_is_not_re_ingested_no_loop():
    conversation_id = uuid4()
    bot_user_id = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(
        bot_conversations={conversation_id},
        bot_user_id=bot_user_id,
        pipeline=pipeline,
    )

    # The bot's OWN outbound message also fires the post-send hook.
    hook.on_sent(
        _FakeRow(
            conversation_id=conversation_id,
            sender_id=bot_user_id,
            body="Hello! I'm the bot.",
        )
    )

    assert pipeline.handled == []


def test_message_in_a_conversation_without_the_bot_is_never_ingested():
    bot_user_id = uuid4()
    bot_conversation_id = uuid4()
    human_to_human_conversation_id = uuid4()
    human_a = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(
        bot_conversations={bot_conversation_id},
        bot_user_id=bot_user_id,
        pipeline=pipeline,
    )

    # A human↔human E2E chat the bot is NOT part of — must be left untouched.
    hook.on_sent(
        _FakeRow(
            conversation_id=human_to_human_conversation_id,
            sender_id=human_a,
            body="this is private",
            protocol="e2e_v1",
        )
    )

    assert pipeline.handled == []


def test_hook_is_inert_when_bot_user_not_provisioned():
    """``resolve_bot_user_id`` returns None (not provisioned) → never ingest:
    the bridge stays safely inert."""
    conversation_id = uuid4()
    pipeline = _CapturingPipeline()
    hook = MeinchatInboundHook(
        is_bot_in_conversation=lambda _: True,
        resolve_bot_user_id=lambda: None,
        build_pipeline=lambda: pipeline,
    )
    hook.on_sent(
        _FakeRow(conversation_id=conversation_id, sender_id=uuid4(), body="/hello")
    )
    assert pipeline.handled == []


def test_inbound_hook_satisfies_post_send_hook_port():
    from plugins.meinchat.meinchat.extensibility.pipeline import IPostSendHook

    hook = _hook(
        bot_conversations={uuid4()},
        bot_user_id=uuid4(),
        pipeline=_CapturingPipeline(),
    )
    assert isinstance(hook, IPostSendHook)


def test_dispatch_round_trip_passes_neutral_inbound():
    """A full hook → pipeline call surfaces the raw the provider will parse —
    a smoke check that the wiring composes (provider.parse_update is exercised
    by the provider unit specs)."""
    conversation_id = uuid4()
    human_sender = uuid4()
    captured = {}

    class _Pipeline:
        def handle_raw_update(self, raw):
            captured["raw"] = raw
            return BotReply(text="done")

    hook = _hook(
        bot_conversations={conversation_id},
        bot_user_id=uuid4(),
        pipeline=_Pipeline(),
    )
    hook.on_sent(
        _FakeRow(
            conversation_id=conversation_id,
            sender_id=human_sender,
            body="/help",
        )
    )
    assert captured["raw"]["body"] == "/help"
