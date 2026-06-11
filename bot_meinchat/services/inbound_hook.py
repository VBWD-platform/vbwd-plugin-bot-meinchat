"""MeinchatInboundHook — the in-process inbound transport (an ``IPostSendHook``).

There is no webhook, long-poll or secret-token for meinchat: the bridge is fully
in-process. meinchat fires ``IPostSendHook.on_sent(row)`` after *every* message
send; this hook is the bot's inbound edge. It ingests a row ONLY when

  * the row lands in a conversation where the configured bot user is a
    participant (so any user who finds the bot and opens a chat is answered in
    THAT conversation — not a single pre-set ``bot_conversation_id``) AND
  * the sender is not the bot user itself (so the bot's own replies never loop).

Every other conversation — every human↔human (E2E) chat the bot is NOT part of —
and the bot's own outbound rows are left completely untouched: the bridge never
reads them.

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
    ) -> None:
        self._is_bot_in_conversation = is_bot_in_conversation
        self._resolve_bot_user_id = resolve_bot_user_id
        self._build_pipeline = build_pipeline

    def on_sent(self, row: Any, *, fetched_by: Any = None) -> None:
        """Ingest ``row`` iff it is a user message in a conversation the bot is
        part of."""
        del fetched_by  # bot ingestion does not depend on the delivery fetcher
        if not self._is_bot_inbound(row):
            return
        raw = {
            "conversation_id": str(row.conversation_id),
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
        """True only for a user message in a conversation the bot is part of."""
        bot_user_id = self._resolve_bot_user_id()
        if bot_user_id is None:
            return False  # not provisioned yet — stay inert.
        # The bot's own outbound replies also fire this hook — never re-ingest.
        if str(row.sender_id) == str(bot_user_id):
            return False
        return self._is_bot_in_conversation(row.conversation_id)
