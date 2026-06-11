"""BotConversationStyle exchanger for the S46 data-exchange seam (S70.2).

Exposes the portable bot-conversation style through the core
``EntityExchanger`` contract so it appears on the generic Settings →
Import/Export page (``settings`` cluster) and round-trips JSON/CSV to another
instance — copy the bot look across instances with the tooling we already
built.

Design notes:

* **DRY** — reuses :class:`BaseModelExchanger`; only the narrow
  ``_SessionModelRepository`` adapter is added (mirrors core / CMS / discount).
* **settings cluster** — a style is a configuration asset, so it inherits the
  ``settings.view`` / ``settings.manage`` gating the registry applies to that
  cluster (no bespoke export/import perm needed).
* **No core change** — registration happens in
  ``BotMeinchatPlugin._register_data_exchangers`` through the shared
  ``db.session``; core imports no ``plugins.*`` module.
"""
from typing import Any, List, Optional

from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger
from vbwd.services.data_exchange.port import CLUSTER_SETTINGS, EntityExchanger
from vbwd.services.data_exchange.registry import data_exchange_registry

ENTITY_KEY_BOT_STYLE = "bot_conversation_styles"
NATURAL_KEY = "name"


class _SessionModelRepository:
    """Narrow model repo satisfying the ``BaseModelExchanger`` contract (ISP).

    Mirrors core's / CMS's / discount's adapter: the domain repository exposes
    finders, not the four flat methods the base exchanger needs.
    """

    def __init__(self, session: Any, model_class: type, natural_key: str) -> None:
        self._session = session
        self._model_class = model_class
        self._natural_key = natural_key

    def find_all(self) -> List[Any]:
        return self._session.query(self._model_class).all()

    def find_by_natural_key(self, value: Any) -> Optional[Any]:
        column = getattr(self._model_class, self._natural_key)
        return self._session.query(self._model_class).filter(column == value).first()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def delete_all(self) -> None:
        self._session.query(self._model_class).delete()


def build_bot_meinchat_exchangers(session: Any) -> List[EntityExchanger]:
    """Construct the bot_meinchat exchangers bound to ``session``."""
    from plugins.bot_meinchat.bot_meinchat.models.conversation_style import (
        BotConversationStyle,
    )

    return [
        BaseModelExchanger(
            entity_key=ENTITY_KEY_BOT_STYLE,
            label="Bot Conversation Style",
            cluster=CLUSTER_SETTINGS,
            natural_key=NATURAL_KEY,
            model_class=BotConversationStyle,
            repository=_SessionModelRepository(
                session, BotConversationStyle, NATURAL_KEY
            ),
            session=session,
            public_fields=["name", "is_active", "tokens"],
            supported_formats=frozenset({"json", "csv"}),
        ),
    ]


def register_bot_meinchat_exchangers(session: Any) -> None:
    """Register the bot_meinchat exchangers into the registry (idempotent).

    Called from ``BotMeinchatPlugin._register_data_exchangers``. Re-registering
    replaces by key, so a repeat enable (per-test app) is clear-safe.
    """
    for exchanger in build_bot_meinchat_exchangers(session):
        data_exchange_registry.register(exchanger)
