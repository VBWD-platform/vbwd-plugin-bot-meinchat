"""``MeinchatMessageServiceSender`` — production ``IMeinchatMessageSender``.

Wraps meinchat's ``MessageService.send_text`` so the provider posts the bot's
reply as the bot user into the bot conversation. It depends on meinchat (a
declared plugin dependency), never the other way round; the provider itself
depends only on the narrow ``IMeinchatMessageSender`` port.

A session-provider closure (``lambda: db.session``) keeps the sender request-safe
without binding a stale session — the meinchat ``MessageService`` is rebuilt per
send from the active session, matching the per-event pattern meinchat already
uses for its contact-form bridge. ``resolve_bot_user_id`` is likewise lazy so the
bot account is provisioned on first use, never at plugin-enable / app-boot time.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from uuid import UUID


class MeinchatMessageServiceSender:
    """Send the bot's reply through meinchat's ``MessageService`` (DIP)."""

    def __init__(
        self,
        *,
        resolve_bot_user_id: Callable[[], UUID],
        build_message_service: Callable[[], Any],
    ) -> None:
        self._resolve_bot_user_id = resolve_bot_user_id
        self._build_message_service = build_message_service

    def send_text(
        self,
        *,
        conversation_id: UUID,
        body: str,
        protocol_hint: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._build_message_service().send_text(
            conversation_id,
            sender_user_id=self._resolve_bot_user_id(),
            body=body,
            protocol_hint=protocol_hint,
            meta=meta,
        )

    def send_room_text(
        self,
        *,
        room_id: UUID,
        body: str,
        protocol_hint: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """S86.3 D6 — post the bot's reply into a ROOM as the bot user. The bot
        is a room member, so meinchat's room membership check passes."""
        self._build_message_service().send_room_text(
            room_id,
            sender_user_id=self._resolve_bot_user_id(),
            body=body,
            protocol_hint=protocol_hint,
            meta=meta,
        )
