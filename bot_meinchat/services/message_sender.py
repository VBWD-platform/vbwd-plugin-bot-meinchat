"""``IMeinchatMessageSender`` — the narrow outbound port the provider depends on.

The provider must post a reply into a meinchat parent (a 1:1 conversation or an
N-party room) without knowing about sessions, repositories, or the full
``MessageService`` surface (ISP / DIP). This port carries exactly the two methods
the provider uses — one per parent kind. The production impl wraps meinchat's
``MessageService.send_text`` / ``send_room_text``; unit tests use an in-memory
fake.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class IMeinchatMessageSender(Protocol):
    """Post one reply into a meinchat conversation OR room as the bot user.

    ``meta`` carries optional S70.0 structured content (e.g. a
    ``bot_choices`` card menu); ``None`` is the plain-body path. ``body`` always
    stays the human-readable + fallback rendering.
    """

    def send_text(
        self,
        *,
        conversation_id: UUID,
        body: str,
        protocol_hint: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...

    def send_room_text(
        self,
        *,
        room_id: UUID,
        body: str,
        protocol_hint: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        ...
