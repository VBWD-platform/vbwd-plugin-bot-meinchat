"""MeinchatInboundHook — the in-process inbound transport (an ``IPostSendHook``).

There is no webhook, long-poll or secret-token for meinchat: the bridge is fully
in-process. meinchat fires ``IPostSendHook.on_sent(row)`` after *every* message
send (1:1 ``send_text`` AND room ``send_room_text``); this hook is the bot's
inbound edge. It ingests a row ONLY when

  * the row lands in a conversation where the configured bot user is a
    participant, OR a ROOM where the bot user is a member (so any user who finds
    the bot — 1:1 or in a widget room — is answered in THAT parent, S86.3 D6),
    AND
  * the sender is not the bot user itself (so the bot's own replies never loop —
    on both the conversation and the room path).

Every other conversation — every human↔human (E2E) chat the bot is NOT part of —
every room the bot is not a member of, and the bot's own outbound rows are left
completely untouched: the bridge never reads them.

Ingestion normalizes the row into the neutral dict the provider's
``parse_update`` expects and runs it through bot-base's
:class:`UpdateDispatcher` (assembled by the inbound pipeline, mirroring the
bot-telegram pattern). A throwing dispatch is contained by meinchat's hook runner
(it logs and never fails the originating send), but we also guard here so a
bridge fault can never corrupt a user's send.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class MeinchatInboundHook:
    """Bridge meinchat's post-send hook into the bot pipeline (any conversation
    the bot user is a participant of).

    ``is_bot_in_conversation`` is a predicate ``(conversation_id) -> bool`` —
    True when the configured bot user is a participant of that conversation. It
    is the participant-based trigger that replaces the single-conversation gate,
    so any user who opens a chat with the bot gets answered in their own
    conversation. It is injected (DI) and resolved per call from the active
    session, so the hook never captures a stale session.

    ``resolve_bot_user_id`` is a zero-arg callable returning the bot user's id —
    lazy so the bot account is provisioned on first inbound message, never at
    plugin-enable / app-boot time. It may return ``None`` until provisioned, in
    which case nothing is ingested (the bridge stays safely inert).

    ``is_bot_in_room`` is the room-parent counterpart — a predicate
    ``(room_id) -> bool`` True when the configured bot user is a MEMBER of that
    room (S86.3 D6). It mirrors ``is_bot_in_conversation`` and is likewise
    injected (DI) + resolved per call. It defaults to "never a member" so a
    deployment that only does 1:1 bots (and tests that only wire the 1:1
    predicate) behave exactly as before (Liskov).

    ``build_pipeline`` is a zero-arg factory returning an object with a
    ``handle_raw_update(raw: dict)`` method (the bot inbound pipeline), built per
    call from the active request session so it never captures a stale session.
    """

    def __init__(
        self,
        *,
        is_bot_in_conversation: Callable[[UUID], bool],
        resolve_bot_user_id: Callable[[], Optional[UUID]],
        build_pipeline: Callable[[], Any],
        is_bot_in_room: Optional[Callable[[UUID], bool]] = None,
    ) -> None:
        self._is_bot_in_conversation = is_bot_in_conversation
        self._is_bot_in_room = is_bot_in_room or (lambda _room_id: False)
        self._resolve_bot_user_id = resolve_bot_user_id
        self._build_pipeline = build_pipeline

    def on_sent(self, row: Any, *, fetched_by: Any = None) -> None:
        """Ingest ``row`` iff it is a user message in a conversation the bot is a
        participant of, or a room the bot is a member of (S86.3 D6)."""
        del fetched_by  # bot ingestion does not depend on the delivery fetcher
        if not self._is_bot_inbound(row):
            return
        room_id = getattr(row, "room_id", None)
        conversation_id = getattr(row, "conversation_id", None)
        raw = {
            "room_id": str(room_id) if room_id is not None else None,
            "conversation_id": (
                str(conversation_id) if conversation_id is not None else None
            ),
            "sender_id": str(row.sender_id),
            "body": row.body,
            "protocol": getattr(row, "protocol", "plain"),
            # S70.0 — a tapped choice card carries a structured action here; the
            # provider lifts it to BotInbound.action_data (no number typed).
            "meta": getattr(row, "meta", None),
        }
        try:
            self._build_pipeline().handle_raw_update(raw)
        except Exception as error:  # a bridge fault must never break the send
            logger.error("bot-meinchat inbound dispatch failed: %s", error)

    def _is_bot_inbound(self, row: Any) -> bool:
        """True only for a user message in a conversation the bot participates in
        or a room the bot is a member of — never the bot's own reply."""
        bot_user_id = self._resolve_bot_user_id()
        if bot_user_id is None:
            return False  # not provisioned yet — stay inert.
        # The bot's own outbound replies also fire this hook — never re-ingest
        # (covers BOTH the conversation and the room path — no loop).
        if str(row.sender_id) == str(bot_user_id):
            return False
        room_id = getattr(row, "room_id", None)
        if room_id is not None:
            return self._is_bot_in_room(room_id)
        return self._is_bot_in_conversation(row.conversation_id)
