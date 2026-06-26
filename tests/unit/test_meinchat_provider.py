"""Unit specs for MeinchatProvider — parse_update / send / identity / choices.

The provider is driven by an in-memory ``IMeinchatMessageSender`` fake and tiny
dict payloads standing in for a meinchat ``Message`` row, proving the provider is
substitutable and meinchat-aware in exactly one place (Liskov / DI). No DB.

Identity is *automatic*: a meinchat sender is already an authenticated vbwd user,
so ``parse_update`` resolves a ``BotIdentity`` directly — there is no ``/start``
link step and ``build_link_deeplink`` returns ``None``.
"""
from uuid import uuid4

from plugins.bot_base.bot_base.ports import IMessengerProvider
from plugins.bot_base.bot_base.types import BotChoice, BotReply, ChatRef
from plugins.bot_meinchat.bot_meinchat.services.meinchat_provider import (
    MeinchatProvider,
    PROVIDER_ID,
)


class _RecordingSender:
    """In-memory ``IMeinchatMessageSender`` capturing every reply send."""

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


def _inbound_payload(*, conversation_id, sender_id, body, protocol="plain"):
    """The neutral dict the adapter's transport hands to ``parse_update``."""
    return {
        "conversation_id": str(conversation_id),
        "sender_id": str(sender_id),
        "body": body,
        "protocol": protocol,
    }


def test_provider_satisfies_messenger_provider_port():
    provider = _provider()
    assert isinstance(provider, IMessengerProvider)
    assert provider.provider_id == PROVIDER_ID == "meinchat"


def test_parse_update_command_maps_to_command_and_args_with_identity():
    conversation_id = uuid4()
    sender_id = uuid4()
    provider = _provider()

    inbound = provider.parse_update(
        _inbound_payload(
            conversation_id=conversation_id,
            sender_id=sender_id,
            body="/draw past present future",
        )
    )

    assert inbound.provider_id == "meinchat"
    assert inbound.chat_ref == ChatRef(
        provider_id="meinchat", chat_id=str(conversation_id)
    )
    assert inbound.sender_ref == str(sender_id)
    assert inbound.command == "draw"
    assert inbound.args == ["past", "present", "future"]
    # Identity is automatic — the meinchat sender IS the vbwd user.
    assert inbound.identity is not None
    assert inbound.identity.provider_id == "meinchat"
    assert inbound.identity.vbwd_user_id == sender_id
    assert inbound.identity.external_user_id == str(sender_id)


def test_parse_update_plain_text_has_no_command_but_keeps_identity():
    conversation_id = uuid4()
    sender_id = uuid4()
    inbound = _provider().parse_update(
        _inbound_payload(
            conversation_id=conversation_id, sender_id=sender_id, body="hello there"
        )
    )
    assert inbound.command is None
    assert inbound.text == "hello there"
    assert inbound.identity.vbwd_user_id == sender_id


def test_parse_update_numbered_choice_tap_maps_to_action_data():
    """A user replying with the printed choice number resolves to the matching
    action_data — the meinchat fallback for native buttons."""
    conversation_id = uuid4()
    sender_id = uuid4()
    provider = _provider()

    # The previous reply offered two choices; the adapter remembers them per chat.
    provider.remember_choices(
        ChatRef(provider_id="meinchat", chat_id=str(conversation_id)),
        [
            BotChoice(label="Reveal", action_data="tarot:reveal:1"),
            BotChoice(label="Cancel", action_data="bot-base:cancel:0"),
        ],
    )

    inbound = provider.parse_update(
        _inbound_payload(conversation_id=conversation_id, sender_id=sender_id, body="2")
    )

    assert inbound.action_data == "bot-base:cancel:0"
    assert inbound.command is None


def test_send_posts_a_meinchat_message_as_plain():
    sender = _RecordingSender()
    provider = _provider(sender=sender)
    conversation_id = uuid4()

    provider.send(
        BotReply(text="Hello!"),
        to=ChatRef(provider_id="meinchat", chat_id=str(conversation_id)),
    )

    assert len(sender.sent) == 1
    call = sender.sent[0]
    assert str(call["conversation_id"]) == str(conversation_id)
    assert call["body"] == "Hello!"
    assert call["protocol_hint"] == "plain"


def test_send_renders_choices_as_numbered_text_fallback():
    sender = _RecordingSender()
    provider = _provider(sender=sender)
    conversation_id = uuid4()
    reply = BotReply(
        text="Pick one",
        choices=[
            BotChoice(label="Reveal", action_data="tarot:reveal:1"),
            BotChoice(label="Cancel", action_data="bot-base:cancel:0"),
        ],
    )

    provider.send(
        reply, to=ChatRef(provider_id="meinchat", chat_id=str(conversation_id))
    )

    body = sender.sent[0]["body"]
    assert "Pick one" in body
    assert "1. Reveal" in body
    assert "2. Cancel" in body


def test_build_link_deeplink_returns_none_identity_is_automatic():
    # No /start linking — meinchat identity is auth-native.
    assert _provider().build_link_deeplink("tok-123") is None
