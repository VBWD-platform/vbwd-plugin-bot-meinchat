"""``IMeinchatMessageSender`` — the narrow outbound port the provider depends on.

The provider must post a reply into a meinchat conversation without knowing about
sessions, repositories, or the full ``MessageService`` surface (ISP / DIP). This
port carries exactly the one method the provider uses. The production impl wraps
meinchat's ``MessageService.send_text``; unit tests use an in-memory fake.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class IMeinchatMessageSender(Protocol):
    """Post one reply into a meinchat conversation as the bot user.

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
