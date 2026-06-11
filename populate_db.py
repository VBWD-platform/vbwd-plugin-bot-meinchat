"""bot_meinchat demo data — idempotent seeder.

Seeds the one default bot-conversation style through the seed service (never
raw SQL) so the fe-user has an active style to read at
``GET /bot-conversation-style/active`` out of the box.
"""
import logging

from vbwd.extensions import db

logger = logging.getLogger(__name__)


def populate(app=None):
    """Seed the default bot-conversation style (idempotent)."""
    from plugins.bot_meinchat.bot_meinchat.services.style_seed import (
        seed_default_style,
    )

    seed_default_style(db.session)
    db.session.commit()
    logger.info("[bot-meinchat] default conversation style ensured")
