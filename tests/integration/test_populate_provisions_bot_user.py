"""S86.x — populate eagerly provisions the assistant BOT user (idempotent).

The bot-widget (S86.3) resolves member nicknames (e.g. ``assistant``) to users
at ``widget/start``. ``bot_meinchat`` provisions its bot user *lazily* (only on
the first 1:1 inbound, via ``_resolve_bot_user_id`` →
``BotSenderProvisioner.ensure_bot_sender``), so the ``assistant`` user/nickname
does not exist until someone DMs it — and ``widget/start`` 404s ``unknown
member``. This characterises the fix: ``populate()`` must eagerly provision the
configured bot user + nickname through the SAME provisioner, idempotently, and
NOT touch ``on_enable`` (which stays DB-free at boot).

Real Postgres (goes through the provisioner + UserService + NicknameService).
"""
from plugins.bot_meinchat import DEFAULT_CONFIG
from plugins.bot_meinchat import populate_db as bot_populate

from vbwd.models.enums import UserRole
from vbwd.repositories.user_repository import UserRepository


def _configured_email_and_nickname() -> tuple[str, str]:
    return DEFAULT_CONFIG["bot_user_email"], DEFAULT_CONFIG["bot_nickname"]


def _clear_assistant_state(session, nickname: str) -> None:
    """Make this test order-independent: the shared ``db`` fixture only truncates
    the style table, so sibling specs (e.g. the round-trip) can leave a bot user
    holding the ``assistant`` nickname. Drop any row owning that nickname so the
    populate path starts from a clean slate."""
    from plugins.meinchat.meinchat.models.user_nickname import UserNickname

    session.query(UserNickname).filter(UserNickname.nickname == nickname).delete()
    session.commit()


def test_populate_provisions_bot_user_with_nickname(app, db):
    email, nickname = _configured_email_and_nickname()
    _clear_assistant_state(db.session, nickname)

    bot_populate.populate()

    user = UserRepository(db.session).find_by_email(email)
    assert user is not None, "populate should create the configured bot user"
    assert user.role == UserRole.BOT

    from plugins.meinchat.meinchat.repositories.nickname_repository import (
        NicknameRepository,
    )

    owned = NicknameRepository(db.session).find_by_nickname_ci(nickname)
    assert owned is not None, "populate should set the configured bot nickname"
    assert owned.user_id == user.id


def test_populate_is_idempotent_no_duplicate_bot_user(app, db):
    email, nickname = _configured_email_and_nickname()
    _clear_assistant_state(db.session, nickname)

    bot_populate.populate()
    bot_populate.populate()

    from sqlalchemy import func

    from vbwd.models.user import User

    count = db.session.query(func.count(User.id)).filter(User.email == email).scalar()
    assert count == 1, "re-running populate must not duplicate the bot user"

    from plugins.meinchat.meinchat.models.user_nickname import UserNickname

    nickname_count = (
        db.session.query(func.count(UserNickname.id))
        .filter(UserNickname.nickname == nickname)
        .scalar()
    )
    assert nickname_count == 1, "re-running populate must not duplicate the nickname"
