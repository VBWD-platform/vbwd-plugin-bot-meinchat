"""S(install) — ``bot_meinchat.populate_db`` exposes the dev-install contract.

The ``dev-install-ce.sh`` fallback runner does, inside its own app context::

    from plugins.bot_meinchat.populate_db import populate_db
    populate_db()

so the module MUST expose a module-level callable ``populate_db()`` that seeds
*assuming an active Flask app context* (no app creation of its own). This guards
that contract (import-level) AND proves the in-context call provisions the
configured ``assistant`` BOT user idempotently — mirroring
``test_populate_provisions_bot_user`` but through the new entrypoint.

Real Postgres (goes through the provisioner + UserService + NicknameService).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY (``populate_db`` delegates to the existing
``populate``); Liskov; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin bot_meinchat --full``.
"""
from plugins.bot_meinchat import DEFAULT_CONFIG
from plugins.bot_meinchat import populate_db as bot_populate_module

from vbwd.models.enums import UserRole
from vbwd.repositories.user_repository import UserRepository


def _configured_email_and_nickname() -> tuple[str, str]:
    return DEFAULT_CONFIG["bot_user_email"], DEFAULT_CONFIG["bot_nickname"]


def _clear_assistant_state(session, nickname: str) -> None:
    from plugins.meinchat.meinchat.models.user_nickname import UserNickname

    session.query(UserNickname).filter(UserNickname.nickname == nickname).delete()
    session.commit()


def test_module_exposes_callable_populate_db():
    """The dev-install fallback imports this exact name — guard it can't
    silently regress."""
    assert callable(getattr(bot_populate_module, "populate_db", None))


def test_populate_db_provisions_bot_user(app, db):
    email, nickname = _configured_email_and_nickname()
    _clear_assistant_state(db.session, nickname)

    bot_populate_module.populate_db()

    user = UserRepository(db.session).find_by_email(email)
    assert user is not None, "populate_db should create the configured bot user"
    assert user.role == UserRole.BOT

    from plugins.meinchat.meinchat.repositories.nickname_repository import (
        NicknameRepository,
    )

    owned = NicknameRepository(db.session).find_by_nickname_ci(nickname)
    assert owned is not None, "populate_db should set the configured bot nickname"
    assert owned.user_id == user.id


def test_populate_db_is_idempotent(app, db):
    email, nickname = _configured_email_and_nickname()
    _clear_assistant_state(db.session, nickname)

    bot_populate_module.populate_db()
    bot_populate_module.populate_db()

    from sqlalchemy import func

    from vbwd.models.user import User

    count = db.session.query(func.count(User.id)).filter(User.email == email).scalar()
    assert count == 1, "re-running populate_db must not duplicate the bot user"
