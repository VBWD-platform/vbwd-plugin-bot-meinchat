"""bot-meinchat plugin — the second ``IMessengerProvider`` (in-process, D9).

It PROVES the bot-base abstraction (D6/D10): the same ``chat`` / ``taro``
consumers light up *inside meinchat* with zero consumer edit. The contrasts with
Telegram are the evidence the seam is provider-neutral:

* **In-process transport** — no webhook, no long-poll, no secret-token. The bot's
  inbound edge is a meinchat ``IPostSendHook`` that ingests messages **only** in
  conversations where the configured bot user is a participant; every other
  human↔human chat is untouched. The bot is a real, findable meinchat user with
  role BOT — any user can find it in search and start a conversation, and the
  bot answers in that conversation.
* **Automatic identity** — a meinchat sender is already an authenticated vbwd
  user, so there is no ``/start`` linking and no ``bot_base_link`` row.
* **Adaptive crypto** — ``plain`` when meinchat-plus is absent (this sub-sprint's
  primary deliverable, sufficient to prove cross-provider parity), ``e2e_v1``
  when a real device directory is registered (selection only; the server-side
  bot-device decrypt is flagged 45.5.1 — meinchat-plus's codec holds no keys).

``dependencies=["bot-base", "meinchat"]``. meinchat-plus is an **optional**
runtime capability — detected via the registered device-directory seam, never
hard-imported.

The plugin class lives **here** (not re-exported).
"""
import logging
from typing import Any, Dict, Optional, TYPE_CHECKING
from uuid import UUID

from flask import current_app

from vbwd.plugins.base import BasePlugin, PluginMetadata

if TYPE_CHECKING:
    from flask import Blueprint

    from plugins.bot_meinchat.bot_meinchat.services.inbound_hook import (
        MeinchatInboundHook,
    )

logger = logging.getLogger(__name__)


DEFAULT_CONFIG: Dict[str, Any] = {
    "debug_mode": False,
    # Master switch for the in-process bridge. When false the post-send hook is
    # inert and no message is ever ingested.
    "enabled": True,
    # The designated bot user's email. This is a real, findable meinchat user
    # with role BOT (provisioned through services — never raw SQL). Any user can
    # find this account in meinchat's nickname search and open a conversation
    # with it; the bot answers in THAT conversation. Empty → the bridge stays
    # inert (no human chat is ever read).
    "bot_user_email": "bot-meinchat@bot.local",
    # The bot's meinchat nickname (how users find it in search).
    "bot_nickname": "assistant",
    # Legacy / optional: a single pre-set conversation id. Retained for backward
    # compatibility but no longer the trigger — the bridge now answers in ANY
    # conversation the bot user is a participant of. Empty by default.
    "bot_conversation_id": "",
}


class BotMeinchatPlugin(BasePlugin):
    """meinchat messenger provider: in-process transport, auto-identity."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="bot-meinchat",
            version="1.0.0",
            author="VBWD Team",
            description=(
                "meinchat messenger provider for the bot bridge: in-process "
                "transport (a meinchat post-send hook scoped to conversations "
                "the bot user participates in), automatic vbwd identity, and "
                "adaptive plain/e2e protocol — self-registers into bot-base's "
                "provider registry."
            ),
            dependencies=["bot-base", "meinchat"],
        )

    def __init__(self) -> None:
        super().__init__()
        self._inbound_hook: Optional["MeinchatInboundHook"] = None
        self._cached_bot_user_id: Optional[UUID] = None

    def initialize(self, config: Optional[Dict[str, Any]] = None) -> None:
        merged = {**DEFAULT_CONFIG}
        if config:
            merged.update(config)
        super().initialize(merged)

    def get_blueprint(self) -> Optional["Blueprint"]:
        # S70.2 — the bot-conversation style surface (admin CRUD + public
        # active-style read). The in-process message transport stays
        # webhook-free; this blueprint serves only the portable style.
        from plugins.bot_meinchat.bot_meinchat.routes import bot_meinchat_bp

        return bot_meinchat_bp

    def get_url_prefix(self) -> str:
        # Multiple prefixes (public + admin) → empty prefix, absolute routes.
        return ""

    @property
    def admin_permissions(self):
        return [
            {
                "key": "bot_meinchat.manage",
                "label": "Manage the meinchat bot",
                "group": "Bot",
            },
        ]

    def _register_data_exchangers(self) -> None:
        """Register the bot-conversation-style exchanger into the S46 seam.

        Core declares none of these (it stays agnostic); the plugin adds them on
        enable through the shared ``db.session`` so the portable style appears on
        the generic Settings → Import/Export page. Guarded like shop's: a missing
        data-exchange seam never breaks enable. Re-registering replaces by key
        (per-test app re-enable is clear-safe).
        """
        try:
            from vbwd.extensions import db
            from plugins.bot_meinchat.bot_meinchat.services.data_exchange.bot_meinchat_exchangers import (  # noqa: E501
                register_bot_meinchat_exchangers,
            )

            register_bot_meinchat_exchangers(db.session)
        except Exception as exchanger_error:  # noqa: BLE001 — optional seam
            logger.warning(
                "[bot-meinchat] Failed to register data exchangers: %s",
                exchanger_error,
            )

    def on_enable(self) -> None:
        from plugins.meinchat.meinchat.extensibility import registry
        from plugins.meinchat.meinchat.extensibility.pipeline import IPostSendHook
        from plugins.bot_meinchat.bot_meinchat.services.inbound_hook import (
            MeinchatInboundHook,
        )
        from plugins.bot_meinchat.bot_meinchat.services.meinchat_provider import (
            MeinchatProvider,
        )

        # Ensure the style model is imported so create_all / metadata see it.
        import plugins.bot_meinchat.bot_meinchat.models  # noqa: F401

        # S70.2 — DI: register the style repository as a container provider so
        # routes / other code resolve it through the container (never a direct
        # construct). Guarded — the seam is optional during boot.
        self._register_style_repository()

        # S70.2 — expose the portable style on Settings → Import/Export.
        self._register_data_exchangers()

        container = getattr(current_app, "container", None)
        if container is None:
            return
        provider_registry = getattr(container, "messenger_provider_registry", None)
        if provider_registry is None:
            return  # bot-base not enabled; nothing to self-register into.

        if not self._config_value("enabled", True):
            return

        # Register WITHOUT any DB work — provisioning the bot user is lazy (on
        # first inbound/outbound message), so plugin-enable / app-boot never
        # touches the session (which may be mid-transaction during boot).
        message_sender = self._build_message_sender()
        provider = MeinchatProvider(message_sender=message_sender)
        provider_registry().register(provider)

        plugin_manager = getattr(current_app, "plugin_manager", None)
        self._inbound_hook = MeinchatInboundHook(
            is_bot_in_conversation=self._is_bot_in_conversation,
            resolve_bot_user_id=self._resolve_bot_user_id,
            build_pipeline=self._pipeline_builder(provider, plugin_manager),
        )
        registry.register(IPostSendHook, self._inbound_hook)

    def on_disable(self) -> None:
        from plugins.meinchat.meinchat.extensibility import registry
        from plugins.meinchat.meinchat.extensibility.pipeline import IPostSendHook
        from plugins.bot_meinchat.bot_meinchat.services.meinchat_provider import (
            PROVIDER_ID,
        )

        if self._inbound_hook is not None:
            registry.unregister(IPostSendHook, self._inbound_hook)
            self._inbound_hook = None

        container = getattr(current_app, "container", None)
        if container is None:
            return

        from vbwd.plugins.di_helpers import unregister_repositories

        unregister_repositories(container, [self._STYLE_REPOSITORY_PROVIDER])

        from plugins.bot_meinchat.bot_meinchat.services.data_exchange.bot_meinchat_exchangers import (  # noqa: E501
            ENTITY_KEY_BOT_STYLE,
        )
        from vbwd.services.data_exchange.registry import data_exchange_registry

        data_exchange_registry.unregister(ENTITY_KEY_BOT_STYLE)

        provider_registry = getattr(container, "messenger_provider_registry", None)
        if provider_registry is not None:
            provider_registry().unregister(PROVIDER_ID)

    _STYLE_REPOSITORY_PROVIDER = "bot_meinchat_conversation_style_repository"

    def _register_style_repository(self) -> None:
        """Register the style repository as a container provider (DI)."""
        container = getattr(current_app, "container", None)
        if container is None:
            return
        from vbwd.plugins.di_helpers import register_repositories
        from plugins.bot_meinchat.bot_meinchat.repositories.conversation_style_repository import (  # noqa: E501
            BotConversationStyleRepository,
        )

        register_repositories(
            container,
            {self._STYLE_REPOSITORY_PROVIDER: BotConversationStyleRepository},
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    def _config_value(self, key: str, default):
        return self._config.get(key, default) if self._config else default

    def _is_bot_in_conversation(self, conversation_id: UUID) -> bool:
        """True when the configured bot user is a participant of ``conversation_id``.

        This is the participant-based inbound trigger: it routes the bot's reply
        into whichever conversation a user opened with it. It reads through
        meinchat's ConversationService (single source for membership) off the
        active request session, so it never captures a stale session and never
        re-implements the pair-membership rule (DRY)."""
        bot_user_id = self._resolve_bot_user_id()
        if bot_user_id is None:
            return False

        from vbwd.extensions import db
        from plugins.meinchat.meinchat.repositories.conversation_repository import (
            ConversationRepository,
        )
        from plugins.meinchat.meinchat.services.conversation_service import (
            ConversationService,
        )

        service = ConversationService(ConversationRepository(db.session))
        conversation = service.get_by_id(conversation_id)
        if conversation is None:
            return False
        return ConversationService.is_member(bot_user_id, conversation)

    def _pipeline_builder(self, provider, plugin_manager):
        from plugins.bot_meinchat.bot_meinchat.services.inbound_pipeline import (
            MeinchatInboundPipeline,
            build_update_dispatcher,
        )

        def build_pipeline() -> MeinchatInboundPipeline:
            from vbwd.extensions import db

            dispatcher = build_update_dispatcher(db.session, plugin_manager)
            return MeinchatInboundPipeline(provider, dispatcher)

        return build_pipeline

    def _build_message_sender(self):
        from plugins.bot_meinchat.bot_meinchat.services.meinchat_message_sender import (  # noqa: E501
            MeinchatMessageServiceSender,
        )

        return MeinchatMessageServiceSender(
            resolve_bot_user_id=self._resolve_bot_user_id,
            build_message_service=self._build_meinchat_message_service,
        )

    @staticmethod
    def _build_meinchat_message_service():
        """Rebuild meinchat's MessageService off the active request session,
        wired to meinchat's SSE/Redis bus so the bot reply reaches a live
        stream (matching meinchat's own contact-form bridge)."""
        from vbwd.extensions import db
        from plugins.meinchat.meinchat.repositories.conversation_repository import (
            ConversationRepository,
        )
        from plugins.meinchat.meinchat.repositories.message_repository import (
            MessageRepository,
        )
        from plugins.meinchat.meinchat.repositories.nickname_repository import (
            NicknameRepository,
        )
        from plugins.meinchat.meinchat.routes import _event_bus
        from plugins.meinchat.meinchat.services.message_service import MessageService

        session = db.session
        return MessageService(
            conv_repo=ConversationRepository(session),
            message_repo=MessageRepository(session),
            nickname_repo=NicknameRepository(session),
            event_bus=_event_bus(),
        )

    def _resolve_bot_user_id(self) -> Optional[UUID]:
        """Provision (idempotently, through meinchat's service) the BOT user
        backing the bot's meinchat identity and return its id. Cached after the
        first successful resolution so steady-state sends do no extra work."""
        if self._cached_bot_user_id is not None:
            return self._cached_bot_user_id

        # Resolve the designated bot user FIRST — a blank email keeps the bridge
        # inert without ever touching the app context / container / session.
        email = str(
            self._config_value("bot_user_email", DEFAULT_CONFIG["bot_user_email"]) or ""
        ).strip()
        if not email:
            return None  # no bot user designated — the bridge stays inert.
        nickname = str(
            self._config_value("bot_nickname", DEFAULT_CONFIG["bot_nickname"])
        )

        from vbwd.extensions import db
        from plugins.meinchat.meinchat.repositories.nickname_repository import (
            NicknameRepository,
        )
        from plugins.meinchat.meinchat.services.bot_sender_provisioner import (
            BotSenderProvisioner,
        )
        from plugins.meinchat.meinchat.services.nickname_service import NicknameService

        container = getattr(current_app, "container", None)
        if container is None:
            return None
        try:
            user_service = container.user_service()
        except Exception:  # noqa: BLE001 — optional bridge, degrade gracefully
            return None

        from vbwd.repositories.user_repository import UserRepository

        session = db.session
        provisioner = BotSenderProvisioner(
            user_service=user_service,
            user_repository=UserRepository(session),
            nickname_service=NicknameService(NicknameRepository(session)),
            session=session,
        )
        try:
            self._cached_bot_user_id = provisioner.ensure_bot_sender(email, nickname)
            return self._cached_bot_user_id
        except Exception as error:  # noqa: BLE001 — never break the send
            logger.warning("[bot-meinchat] bot provisioning failed: %s", error)
            return None
