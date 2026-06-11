"""Integration: BotConversationStyle model + repository (real PG) — S70.2.

* exactly-one-active invariant: ``set_active`` clears the others.
* ``find_active`` / ``find_by_name`` return the expected rows.
* the default-style seed is idempotent (running twice leaves one default).

Data is created through the repository / seed service (no raw SQL). The shared
``db`` fixture creates + drops the test tables.
"""
from plugins.bot_meinchat.bot_meinchat.models.conversation_style import (
    BotConversationStyle,
)
from plugins.bot_meinchat.bot_meinchat.repositories.conversation_style_repository import (  # noqa: E501
    BotConversationStyleRepository,
)
from plugins.bot_meinchat.bot_meinchat.services.style_seed import seed_default_style


def _repo(db):
    return BotConversationStyleRepository(db.session)


def _add(db, name, *, is_active=False, tokens=None):
    repo = _repo(db)
    style = BotConversationStyle(
        name=name, is_active=is_active, tokens=tokens or {"accent": "#3182ce"}
    )
    repo.add(style)
    db.session.commit()
    return style


class TestExactlyOneActive:
    def test_set_active_clears_others(self, db):
        first = _add(db, "first", is_active=True)
        second = _add(db, "second", is_active=False)

        repo = _repo(db)
        repo.set_active(second.id)
        db.session.commit()

        assert _repo(db).find_by_name("first").is_active is False
        assert _repo(db).find_by_name("second").is_active is True
        assert _repo(db).find_active().id == second.id
        # de-dup guard: only one active across the table.
        actives = (
            db.session.query(BotConversationStyle)
            .filter(BotConversationStyle.is_active.is_(True))
            .all()
        )
        assert len(actives) == 1
        assert first  # referenced

    def test_find_active_returns_none_when_no_active(self, db):
        _add(db, "inactive-only", is_active=False)
        assert _repo(db).find_active() is None


class TestDefaultSeedIdempotent:
    def test_seed_twice_leaves_one_default(self, db):
        seed_default_style(db.session)
        db.session.commit()
        seed_default_style(db.session)
        db.session.commit()

        rows = db.session.query(BotConversationStyle).all()
        assert len(rows) == 1
        default = rows[0]
        assert default.is_active is True
        assert default.tokens  # the default ships some `--vbwd-botchat-*` vars
