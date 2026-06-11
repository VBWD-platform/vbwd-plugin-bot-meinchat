"""Seed the one default bot-conversation style (idempotent, via the repo).

Gives the fe-user something to read at ``GET /bot-conversation-style/active``
out of the box. Idempotent: if a style named ``Default`` already exists the seed
is a no-op (never raw SQL, never a second default). Called from
``populate_db`` and from the plugin's ``on_enable`` provisioning path.
"""
from plugins.bot_meinchat.bot_meinchat.models.conversation_style import (
    BotConversationStyle,
)
from plugins.bot_meinchat.bot_meinchat.repositories.conversation_style_repository import (  # noqa: E501
    BotConversationStyleRepository,
)
from plugins.bot_meinchat.bot_meinchat.services.style_token_validation import (
    sanitise_style_tokens,
)

DEFAULT_STYLE_NAME = "Default"

# The shipped default `--vbwd-botchat-*` palette (matches S70.1's fe-user
# defaults). Whitelisted + safe by construction (validated on seed too).
DEFAULT_STYLE_TOKENS = {
    "card_bg": "#ffffff",
    "card_border": "#e2e8f0",
    "card_radius": "12px",
    "card_fg": "#1a202c",
    "accent": "#3182ce",
    "badge_bg": "#3182ce",
    "badge_fg": "#ffffff",
    "hint": "#718096",
    "gap": "8px",
}


def seed_default_style(session) -> BotConversationStyle:
    """Ensure exactly one ``Default`` style exists and is active.

    Returns the default row (existing or newly created). Idempotent — a second
    call finds the existing row and leaves the table unchanged.
    """
    repository = BotConversationStyleRepository(session)
    existing = repository.find_by_name(DEFAULT_STYLE_NAME)
    if existing is not None:
        return existing

    style = BotConversationStyle(
        name=DEFAULT_STYLE_NAME,
        is_active=True,
        tokens=sanitise_style_tokens(DEFAULT_STYLE_TOKENS),
    )
    repository.add(style)
    return style
