"""Data access for ``bot_meinchat_conversation_style`` rows.

Thin wrapper over the SQLAlchemy session. Enforces the exactly-one-active
invariant in ``set_active`` (clears every other row's ``is_active`` first), and
exposes the natural-key + active finders the routes / exchanger need.
"""
from typing import List, Optional
from uuid import UUID

from plugins.bot_meinchat.bot_meinchat.models.conversation_style import (
    BotConversationStyle,
)


class BotConversationStyleRepository:
    """Repository for :class:`BotConversationStyle`."""

    def __init__(self, session) -> None:
        self._session = session

    def find_all(self) -> List[BotConversationStyle]:
        return self._session.query(BotConversationStyle).all()

    def find_by_id(self, style_id) -> Optional[BotConversationStyle]:
        return self._session.get(BotConversationStyle, style_id)

    def find_by_name(self, name: str) -> Optional[BotConversationStyle]:
        return (
            self._session.query(BotConversationStyle)
            .filter(BotConversationStyle.name == name)
            .one_or_none()
        )

    def find_active(self) -> Optional[BotConversationStyle]:
        return (
            self._session.query(BotConversationStyle)
            .filter(BotConversationStyle.is_active.is_(True))
            .first()
        )

    def add(self, style: BotConversationStyle) -> None:
        self._session.add(style)

    def delete(self, style: BotConversationStyle) -> None:
        self._session.delete(style)

    def set_active(self, style_id: UUID) -> Optional[BotConversationStyle]:
        """Make ``style_id`` the single active style.

        Clears ``is_active`` on every other row first (the exactly-one-active
        invariant), then flags the target. Returns the now-active row, or
        ``None`` when ``style_id`` does not exist (the caller decides — a route
        maps that to a 404).
        """
        target = self.find_by_id(style_id)
        if target is None:
            return None
        self._session.query(BotConversationStyle).filter(
            BotConversationStyle.id != style_id
        ).update({BotConversationStyle.is_active: False})
        target.is_active = True
        return target
