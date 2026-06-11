"""S70.0 — structured `meta` on the meinchat bot bridge.

Outbound: a ``BotReply`` with choices emits a structured
``meta = {"kind": "bot_choices", ...}`` AND keeps the numbered-text ``body`` as
the universal fallback (Liskov — a client ignoring ``meta`` sees today's menu).

Inbound: a tapped card arrives as ``meta = {"kind": "bot_action",
"action_data": ...}`` and ``parse_update`` lifts ``action_data`` straight onto
the ``BotInbound`` — no number typed, no per-chat memory needed. Malformed /
absent ``meta`` falls back to body parsing exactly as before (never crashes).
"""
from uuid import uuid4

from plugins.bot_base.bot_base.types import BotChoice, BotReply, ChatRef
from plugins.bot_meinchat.bot_meinchat.services.meinchat_provider import (
    MeinchatProvider,
)


class _RecordingSender:
    """In-memory ``IMeinchatMessageSender`` capturing body + structured meta."""

    def __init__(self) -> None:
        self.sent = []

    def send_text(self, *, conversation_id, body, protocol_hint, meta=None):
        self.sent.append(
            {
                "conversation_id": conversation_id,
                "body": body,
                "protocol_hint": protocol_hint,
                "meta": meta,
            }
        )


def _provider(sender=None):
    return MeinchatProvider(message_sender=sender or _RecordingSender())


def _inbound_payload(*, conversation_id, sender_id, body, protocol="plain", meta=None):
    payload = {
        "conversation_id": str(conversation_id),
        "sender_id": str(sender_id),
        "body": body,
        "protocol": protocol,
    }
    if meta is not None:
        payload["meta"] = meta
    return payload


class TestOutboundMeta:
    def test_choices_emit_bot_choices_meta_with_label_and_action_data(self):
        sender = _RecordingSender()
        provider = _provider(sender=sender)
        reply = BotReply(
            text="Pick one",
            choices=[
                BotChoice(label="Reveal", action_data="taro:reveal:1"),
                BotChoice(label="Cancel", action_data="bot-base:cancel:0"),
            ],
        )

        provider.send(
            reply, to=ChatRef(provider_id="meinchat", chat_id=str(uuid4()))
        )

        meta = sender.sent[0]["meta"]
        assert meta == {
            "kind": "bot_choices",
            "choices": [
                {"label": "Reveal", "action_data": "taro:reveal:1"},
                {"label": "Cancel", "action_data": "bot-base:cancel:0"},
            ],
        }

    def test_choices_keep_numbered_text_body_as_fallback(self):
        sender = _RecordingSender()
        provider = _provider(sender=sender)
        reply = BotReply(
            text="Pick one",
            choices=[BotChoice(label="Reveal", action_data="taro:reveal:1")],
        )

        provider.send(
            reply, to=ChatRef(provider_id="meinchat", chat_id=str(uuid4()))
        )

        body = sender.sent[0]["body"]
        assert "Pick one" in body
        assert "1. Reveal" in body

    def test_plain_reply_without_choices_sends_no_meta(self):
        sender = _RecordingSender()
        provider = _provider(sender=sender)

        provider.send(
            BotReply(text="Hello!"),
            to=ChatRef(provider_id="meinchat", chat_id=str(uuid4())),
        )

        assert sender.sent[0]["meta"] is None
        assert sender.sent[0]["body"] == "Hello!"

    def test_choice_hint_is_included_when_present(self):
        sender = _RecordingSender()
        provider = _provider(sender=sender)

        class _ChoiceWithHint(BotChoice):
            pass

        # The dataclass has no hint; the provider reads it defensively via
        # getattr so a future hint-bearing choice flows through unchanged.
        choice = BotChoice(label="Pro", action_data="subscription:plan:42")
        object.__setattr__(choice, "hint", "€29/mo")
        provider.send(
            BotReply(text="Plans", choices=[choice]),
            to=ChatRef(provider_id="meinchat", chat_id=str(uuid4())),
        )

        assert sender.sent[0]["meta"]["choices"][0]["hint"] == "€29/mo"


class TestInboundMeta:
    def test_bot_action_meta_lifts_action_data_directly(self):
        provider = _provider()
        inbound = provider.parse_update(
            _inbound_payload(
                conversation_id=uuid4(),
                sender_id=uuid4(),
                body="Pro",
                meta={"kind": "bot_action", "action_data": "subscription:plan:42"},
            )
        )
        # No number typed, no remembered choices — the tap carries the action.
        assert inbound.action_data == "subscription:plan:42"
        assert inbound.command is None

    def test_no_meta_falls_back_to_body_command_parsing(self):
        provider = _provider()
        inbound = provider.parse_update(
            _inbound_payload(
                conversation_id=uuid4(), sender_id=uuid4(), body="/draw a b"
            )
        )
        assert inbound.action_data is None
        assert inbound.command == "draw"
        assert inbound.args == ["a", "b"]

    def test_malformed_meta_falls_back_to_body_without_crashing(self):
        provider = _provider()
        sender_id = uuid4()
        for bad_meta in (
            {"kind": "bot_action"},  # missing action_data
            {"kind": "bot_action", "action_data": 42},  # wrong type
            {"kind": "bot_choices", "choices": []},  # not an action
            "not-a-dict",
            {"action_data": "x:y:z"},  # missing kind
        ):
            inbound = provider.parse_update(
                _inbound_payload(
                    conversation_id=uuid4(),
                    sender_id=sender_id,
                    body="hello",
                    meta=bad_meta,
                )
            )
            assert inbound.action_data is None
            assert inbound.text == "hello"
