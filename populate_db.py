"""bot_meinchat demo data — idempotent seeder.

Seeds:

  1. the one default bot-conversation style (so fe-user has an active style to
     read at ``GET /bot-conversation-style/active`` out of the box), and
  2. the designated bot (``assistant``) BOT user + meinchat nickname EAGERLY, so
     a bot-widget that invites the bot by nickname (S86.3 ``widget/start``)
     resolves out of the box instead of 404ing ``unknown member``.

Both steps go through the proper services (never raw SQL) and are idempotent.
Provisioning here is deliberate: the plugin's ``on_enable`` stays DB-free at boot
(provisioning is lazy there); this populate/setup seed is the place to do the
eager provisioning, using the SAME ``BotSenderProvisioner`` mechanism as the
lazy ``_resolve_bot_user_id`` path (DRY).
"""
import logging

from flask import current_app

from vbwd.extensions import db

logger = logging.getLogger(__name__)


def populate(app=None):
    """Seed the default style + eagerly provision the assistant bot user.

    The caller provides the Flask app context (the recipe wraps this in
    ``with app.app_context()``); ``app`` is accepted for symmetry and is unused.
    Both seed steps are idempotent.
    """
    from plugins.bot_meinchat.bot_meinchat.services.style_seed import (
        seed_default_style,
    )

    seed_default_style(db.session)
    db.session.commit()
    logger.info("[bot-meinchat] default conversation style ensured")

    _provision_bot_user()


def _provision_bot_user() -> None:
    """Idempotently provision the configured bot (``assistant``) BOT user +
    nickname through ``BotSenderProvisioner`` (the SAME mechanism the lazy
    ``_resolve_bot_user_id`` path uses). A blank ``bot_user_email`` skips
    provisioning (mirrors the lazy path's inert behaviour)."""
    from plugins.bot_meinchat import DEFAULT_CONFIG

    email = str(DEFAULT_CONFIG["bot_user_email"] or "").strip()
    if not email:
        logger.info("[bot-meinchat] no bot_user_email configured — skipping provision")
        return
    nickname = str(DEFAULT_CONFIG["bot_nickname"])

    from plugins.meinchat.meinchat.repositories.nickname_repository import (
        NicknameRepository,
    )
    from plugins.meinchat.meinchat.services.bot_sender_provisioner import (
        BotSenderProvisioner,
    )
    from plugins.meinchat.meinchat.services.nickname_service import NicknameService
    from vbwd.repositories.user_repository import UserRepository

    container = getattr(current_app, "container", None)
    if container is None:
        logger.warning("[bot-meinchat] no container — skipping bot provision")
        return

    session = db.session
    already_present = UserRepository(session).find_by_email(email) is not None
    provisioner = BotSenderProvisioner(
        user_service=container.user_service(),
        user_repository=UserRepository(session),
        nickname_service=NicknameService(NicknameRepository(session)),
        session=session,
    )
    provisioner.ensure_bot_sender(email, nickname)
    db.session.commit()
    logger.info(
        "[bot-meinchat] assistant %s (@%s, %s)",
        "already present" if already_present else "provisioned",
        nickname,
        email,
    )
