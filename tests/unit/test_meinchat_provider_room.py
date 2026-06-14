"""Unit specs for MeinchatProvider — the ROOM parent (S86.3 D6).

``ChatRef.chat_id`` is opaque and provider-scoped (bot_base stays neutral). The
meinchat provider encodes the PARENT KIND inside its own ``chat_id``: a room
parent is ``"room:<room_id>"`` while a 1:1 conversation parent stays the bare
conversation UUID (unchanged — backward compatible). ``parse_update`` builds the
encoded ref from a raw room dict; ``send`` decodes it and posts the bot reply
into the ROOM via ``IMeinchatMessageSender.send_room_text``.

A different ``chat_id`` per room means bot_base's per-``ChatRef`` ``BotSession``
keys stay correct per-room for free (D7) — the dispatcher needs no room concept.
"""
from uuid import uuid4

from plugins.bot_base.bot_base.types import BotChoice, BotReply, ChatRef
from plugins.bot_meinchat.bot_meinchat.services.meinchat_provider import (
    MeinchatProvider,
)


class _RecordingSender:
    """In-memory ``IMeinchatMessageSender`` capturing conversation + room sends."""

    def __init__(self) -> None:
        self.conversation_sends = []
        self.room_sends = []

    def send_text(self, *, conversation_id, body, protocol_hint, meta=None):
        self.conversation_sends.append(
            {"conversation_id": conversation_id, "body": body, "meta": meta}
        )

    def send_room_text(self, *, room_id, body, protocol_hint, meta=None):
        self.room_sends.append({"room_id": room_id, "body": body, "meta": meta})


def _provider(sender=None):
    return MeinchatProvider(message_sender=sender or _RecordingSender())


def _room_payload(*, room_id, sender_id, body, protocol="plain", meta=None):
    """The neutral dict the room transport hands to ``parse_update`` — note the
    parent is ``room_id`` and ``conversation_id`` is absent/None."""
    return {
        "room_id": str(room_id),
        "conversation_id": None,
        "sender_id": str(sender_id),
        "body": body,
        "protocol": protocol,
        "meta": meta,
    }


def test_parse_update_room_yields_chat_ref_encoding_the_room():
    room_id = uuid4()
    sender_id = uuid4()
    inbound = _provider().parse_update(
        _room_payload(room_id=room_id, sender_id=sender_id, body="/draw a b")
    )

    assert inbound.chat_ref.provider_id == "meinchat"
    # The room parent is encoded in the opaque chat_id; the room UUID is present.
    assert str(room_id) in inbound.chat_ref.chat_id
    assert inbound.chat_ref.chat_id != str(room_id)  # NOT the bare uuid (a room)
    assert inbound.command == "draw"
    assert inbound.args == ["a", "b"]
    assert inbound.identity.vbwd_user_id == sender_id


def test_room_and_conversation_chat_ids_differ_for_distinct_parents():
    """A room ref and a conversation ref are different ChatRefs even if they
    shared a raw id — so per-room BotSession keys never collide (D7)."""
    shared_id = uuid4()
    room_ref = (
        _provider()
        .parse_update(_room_payload(room_id=shared_id, sender_id=uuid4(), body="hi"))
        .chat_ref
    )
    conv_ref = (
        _provider()
        .parse_update(
            {
                "conversation_id": str(shared_id),
                "sender_id": str(uuid4()),
                "body": "hi",
                "protocol": "plain",
            }
        )
        .chat_ref
    )

    assert room_ref != conv_ref


def test_send_to_a_room_ref_posts_via_send_room_text():
    sender = _RecordingSender()
    provider = _provider(sender=sender)
    room_id = uuid4()
    room_ref = provider.parse_update(
        _room_payload(room_id=room_id, sender_id=uuid4(), body="hi")
    ).chat_ref

    provider.send(BotReply(text="Hello room!"), to=room_ref)

    assert sender.conversation_sends == []
    assert len(sender.room_sends) == 1
    call = sender.room_sends[0]
    assert str(call["room_id"]) == str(room_id)
    assert call["body"] == "Hello room!"


def test_send_to_a_conversation_ref_still_posts_via_send_text():
    """Liskov / backward compatibility: a bare-uuid (conversation) ref keeps
    using send_text — the 1:1 path is unchanged."""
    sender = _RecordingSender()
    provider = _provider(sender=sender)
    conversation_id = uuid4()

    provider.send(
        BotReply(text="1:1"),
        to=ChatRef(provider_id="meinchat", chat_id=str(conversation_id)),
    )

    assert sender.room_sends == []
    assert len(sender.conversation_sends) == 1
    assert str(sender.conversation_sends[0]["conversation_id"]) == str(conversation_id)


def test_room_reply_choices_ride_as_meta_and_numbered_fallback():
    sender = _RecordingSender()
    provider = _provider(sender=sender)
    room_id = uuid4()
    room_ref = provider.parse_update(
        _room_payload(room_id=room_id, sender_id=uuid4(), body="menu")
    ).chat_ref

    provider.send(
        BotReply(
            text="Pick one",
            choices=[
                BotChoice(label="Reveal", action_data="taro:reveal:1"),
                BotChoice(label="Cancel", action_data="bot-base:cancel:0"),
            ],
        ),
        to=room_ref,
    )

    call = sender.room_sends[0]
    assert "1. Reveal" in call["body"]
    assert call["meta"]["kind"] == "bot_choices"
