"""Integration: BotConversationStyle data-exchange exchanger (real PG) — S70.2.

* round-trips by ``name`` (export active style → wipe → import → equal).
* appears in the manifest with cluster ``settings`` after registration.

Data is seeded through the repository (no raw SQL); the shared ``db`` fixture
creates + drops the test tables. Mirrors the discount/shop exchanger tests.
"""
from vbwd.services.data_exchange.envelope import build_envelope
from vbwd.services.data_exchange.port import CLUSTER_SETTINGS, ExportSelector
from plugins.bot_meinchat.bot_meinchat.models.conversation_style import (
    BotConversationStyle,
)
from plugins.bot_meinchat.bot_meinchat.repositories.conversation_style_repository import (  # noqa: E501
    BotConversationStyleRepository,
)
from plugins.bot_meinchat.bot_meinchat.services.data_exchange.bot_meinchat_exchangers import (  # noqa: E501
    ENTITY_KEY_BOT_STYLE,
    build_bot_meinchat_exchangers,
)

_TOKENS = {"accent": "#3182ce", "card_bg": "#ffffff", "card_radius": "12px"}


def _exchanger(session):
    by_key = {
        exchanger.entity_key: exchanger
        for exchanger in build_bot_meinchat_exchangers(session)
    }
    return by_key[ENTITY_KEY_BOT_STYLE]


def _seed_style(db, name="Exported", is_active=True, tokens=None):
    style = BotConversationStyle(
        name=name, is_active=is_active, tokens=tokens or dict(_TOKENS)
    )
    BotConversationStyleRepository(db.session).add(style)
    db.session.commit()
    return style


class TestStyleRoundTrip:
    def test_round_trip_by_name(self, db):
        _seed_style(db)
        exchanger = _exchanger(db.session)

        before = exchanger.export(
            ExportSelector(ids=["Exported"]), include_pii=False
        ).rows
        assert before and before[0]["name"] == "Exported"
        assert before[0]["is_active"] is True
        assert before[0]["tokens"] == _TOKENS

        # Wipe into a clean state (another instance), then import.
        db.session.query(BotConversationStyle).filter(
            BotConversationStyle.name == "Exported"
        ).delete()
        db.session.commit()

        payload = build_envelope(ENTITY_KEY_BOT_STYLE, before, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created == 1

        rebuilt = BotConversationStyleRepository(db.session).find_by_name("Exported")
        assert rebuilt is not None
        assert rebuilt.is_active is True
        assert rebuilt.tokens == _TOKENS


class TestRegistration:
    def test_on_enable_registers_exchanger_in_settings_cluster(self, db):
        from vbwd.services.data_exchange.registry import data_exchange_registry
        from plugins.bot_meinchat import BotMeinchatPlugin

        plugin = BotMeinchatPlugin()
        plugin.initialize({})
        plugin._register_data_exchangers()

        by_key = {
            exchanger.entity_key: exchanger
            for exchanger in data_exchange_registry.all()
        }
        assert ENTITY_KEY_BOT_STYLE in by_key
        assert by_key[ENTITY_KEY_BOT_STYLE].cluster == CLUSTER_SETTINGS
