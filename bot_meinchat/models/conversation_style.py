"""BotConversationStyle — a portable, themeable bot-chat look (S70.2).

A first-class entity mapping the fe-user ``--vbwd-botchat-*`` CSS custom
properties (S70.1) to safe string values. Exactly one row is active at a time;
the fe-user reads the active style and applies its ``tokens`` as CSS custom
properties only (never arbitrary CSS — see ``style_token_validation``).

It is exported/imported through the unified S46 data-exchange framework (same
``BaseModelExchanger`` pattern as shop/discount), so the bot look copies across
instances with the tooling we already built.
"""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


class BotConversationStyle(BaseModel):
    """A named, themeable bot-conversation style (one active at a time)."""

    __tablename__ = "bot_meinchat_conversation_style"

    name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    # A whitelisted map of `--vbwd-botchat-*` var -> safe string value. Validated
    # + sanitised on write (style_token_validation) — never arbitrary CSS.
    tokens = db.Column(db.JSON, nullable=False, default=dict)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "is_active": bool(self.is_active),
            "tokens": dict(self.tokens or {}),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
