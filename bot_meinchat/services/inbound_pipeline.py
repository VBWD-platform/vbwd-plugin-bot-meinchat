"""Inbound pipeline — one home for parse → dispatch → send (DRY).

The in-process transport (the meinchat post-send hook) must do the same three
steps with a raw meinchat message: hand it to the provider's ``parse_update``,
route it through bot-base's :class:`UpdateDispatcher`, and send the resulting
:class:`BotReply` back through the provider.

The dispatcher is *built from bot-base's own pieces* (CommandRegistry,
ConversationService, LinkService, BotLinkRepository) per call from the active
``db.session`` — bot-base does not register the dispatcher in the container, so
this adapter assembles it without modifying bot-base (Open/Closed). This mirrors
``bot_telegram``'s ``inbound_pipeline``; the small duplication is the accepted
DRY trade-off (S45.5) rather than a premature shared module.
"""
from __future__ import annotations

from plugins.bot_base.bot_base.repositories.bot_link_repository import (
    BotLinkRepository,
)
from plugins.bot_base.bot_base.repositories.bot_link_token_repository import (
    BotLinkTokenRepository,
)
from plugins.bot_base.bot_base.repositories.bot_session_repository import (
    BotSessionRepository,
)
from plugins.bot_base.bot_base.services.command_registry import CommandRegistry
from plugins.bot_base.bot_base.services.conversation_service import (
    ConversationService,
)
from plugins.bot_base.bot_base.services.link_service import LinkService
from plugins.bot_base.bot_base.services.update_dispatcher import UpdateDispatcher
from plugins.bot_base.bot_base.types import BotInbound, BotReply


def build_update_dispatcher(session, plugin_manager) -> UpdateDispatcher:
    """Assemble bot-base's :class:`UpdateDispatcher` from a session + manager."""
    link_repository = BotLinkRepository(session)
    return UpdateDispatcher(
        command_registry=CommandRegistry(plugin_manager),
        conversation_service=ConversationService(BotSessionRepository(session)),
        link_service=LinkService(link_repository, BotLinkTokenRepository(session)),
        link_repository=link_repository,
    )


class MeinchatInboundPipeline:
    """Run a raw meinchat message through parse → dispatch → send."""

    def __init__(self, provider, dispatcher) -> None:
        self._provider = provider
        self._dispatcher = dispatcher

    def handle_raw_update(self, raw: dict) -> BotReply:
        """Process one raw meinchat message; return the reply that was sent.

        The reply is posted back into the originating conversation through the
        provider, so the caller (the inbound hook) never re-implements delivery.
        """
        inbound: BotInbound = self._provider.parse_update(raw)
        reply = self._dispatcher.dispatch(inbound)
        self._provider.send(reply, to=inbound.chat_ref)
        return reply
