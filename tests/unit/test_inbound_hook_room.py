"""Unit specs for MeinchatInboundHook — the ROOM path (S86.3 D6/D7).

The same in-process transport that answers a 1:1 conversation must also answer a
multi-party ROOM: meinchat fires ``IPostSendHook.on_sent(row)`` after a
``send_room_text``; the hook ingests a room row ONLY when

  * the configured bot user is a MEMBER of that room AND
  * its sender is not the bot itself (the bot's own room reply must not loop).

A room row carries ``room_id`` (and ``conversation_id is None``); the raw dict
the hook builds for the provider therefore carries the room parent. No DB, no net
— the membership predicate is injected (mirroring ``is_bot_in_conversation``).
"""
from uuid import uuid4

from plugins.bot_base.bot_base.types import BotReply
from plugins.bot_meinchat.bot_meinchat.services.inbound_hook import (
    MeinchatInboundHook,
)


class _FakeRoomRow:
    """Minimal stand-in for a meinchat ``Message`` row sent into a room."""

    def __init__(self, *, room_id, sender_id, body, protocol="plain", meta=None):
        self.room_id = room_id
        self.conversation_id = None
        self.sender_id = sender_id
        self.body = body
        self.protocol = protocol
        self.envelope = None
        self.meta = meta


class _CapturingPipeline:
    def __init__(self) -> None:
        self.handled = []

    def handle_raw_update(self, raw: dict) -> BotReply:
        self.handled.append(raw)
        return BotReply(text="ok")


def _hook(*, bot_rooms, bot_user_id, pipeline):
    """Build a hook whose room-membership test is satisfied for any room id in
    ``bot_rooms`` (a set of room ids the bot is a member of). The 1:1 predicate
    is wired to always-False so only the room path is exercised."""
    bot_room_ids = {str(room_id) for room_id in bot_rooms}
    return MeinchatInboundHook(
        is_bot_in_conversation=lambda conversation_id: False,
        is_bot_in_room=lambda room_id: str(room_id) in bot_room_ids,
        resolve_bot_user_id=lambda: bot_user_id,
        build_pipeline=lambda: pipeline,
    )


def test_room_message_from_a_user_in_a_bot_room_is_ingested():
    room_id = uuid4()
    bot_user_id = uuid4()
    human_sender = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(bot_rooms={room_id}, bot_user_id=bot_user_id, pipeline=pipeline)

    hook.on_sent(_FakeRoomRow(room_id=room_id, sender_id=human_sender, body="/hello"))

    assert len(pipeline.handled) == 1
    raw = pipeline.handled[0]
    assert raw["room_id"] == str(room_id)
    assert raw["conversation_id"] is None
    assert raw["sender_id"] == str(human_sender)
    assert raw["body"] == "/hello"


def test_room_message_carries_protocol_and_meta_through():
    room_id = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(bot_rooms={room_id}, bot_user_id=uuid4(), pipeline=pipeline)

    hook.on_sent(
        _FakeRoomRow(
            room_id=room_id,
            sender_id=uuid4(),
            body="2",
            protocol="plain",
            meta={"kind": "bot_action", "action_data": "tarot:reveal:1"},
        )
    )

    raw = pipeline.handled[0]
    assert raw["protocol"] == "plain"
    assert raw["meta"] == {"kind": "bot_action", "action_data": "tarot:reveal:1"}


def test_room_message_where_bot_is_not_a_member_is_never_ingested():
    bot_user_id = uuid4()
    bot_room_id = uuid4()
    other_room_id = uuid4()
    human = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(bot_rooms={bot_room_id}, bot_user_id=bot_user_id, pipeline=pipeline)

    hook.on_sent(_FakeRoomRow(room_id=other_room_id, sender_id=human, body="hi"))

    assert pipeline.handled == []


def test_bot_own_room_reply_is_not_re_ingested_no_loop():
    room_id = uuid4()
    bot_user_id = uuid4()
    pipeline = _CapturingPipeline()
    hook = _hook(bot_rooms={room_id}, bot_user_id=bot_user_id, pipeline=pipeline)

    # The bot's own room reply also fires the post-send hook.
    hook.on_sent(
        _FakeRoomRow(room_id=room_id, sender_id=bot_user_id, body="I'm the bot.")
    )

    assert pipeline.handled == []


def test_room_hook_is_inert_when_bot_user_not_provisioned():
    room_id = uuid4()
    pipeline = _CapturingPipeline()
    hook = MeinchatInboundHook(
        is_bot_in_conversation=lambda _: False,
        is_bot_in_room=lambda _: True,
        resolve_bot_user_id=lambda: None,
        build_pipeline=lambda: pipeline,
    )

    hook.on_sent(_FakeRoomRow(room_id=room_id, sender_id=uuid4(), body="/hello"))

    assert pipeline.handled == []
