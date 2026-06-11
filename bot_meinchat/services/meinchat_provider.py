"""MeinchatProvider — the only meinchat-aware class (an ``IMessengerProvider``).

It normalizes a meinchat message (handed to it as a neutral dict by the in-process
transport) into a neutral :class:`BotInbound`, and renders a neutral
:class:`BotReply` into a meinchat message via the injected
:class:`IMeinchatMessageSender`.

Two contrasts with the Telegram adapter are the *evidence the seam is
provider-neutral* (D6/D10):

* **Identity is automatic.** A meinchat sender is already an authenticated vbwd
  user, so ``parse_update`` attaches a :class:`BotIdentity` directly — there is
  no ``/start`` linking step and ``build_link_deeplink`` returns ``None``.
* **No webhook / poll / secret.** The transport is in-process (a meinchat
  post-send hook); none of that lives in this provider — only parse + send.

Choices render as a numbered text menu (meinchat has no native inline keyboard
in the plain path); a user replying with the choice number is resolved back to
the matching ``action_data``. Remembering a chat's last offered choices is a
small per-process map keyed by :class:`ChatRef`.
"""
from __future__ import annotations

from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from plugins.bot_base.bot_base.types import (
    BotChoice,
    BotIdentity,
    BotInbound,
    BotReply,
    ChatRef,
)
from plugins.bot_meinchat.bot_meinchat.services.message_sender import (
    IMeinchatMessageSender,
)

PROVIDER_ID = "meinchat"
# meinchat conversation rows are server-readable plaintext in the plain path.
OUTBOUND_PROTOCOL_HINT = "plain"


class MeinchatProvider:
    """meinchat adapter implementing the ``IMessengerProvider`` SPI.

    ``message_sender`` is injected (DI) so the provider stays free of session /
    repository wiring and is substitutable with an in-memory fake (Liskov). The
    sender already posts replies as the bot user; the in-process transport (the
    inbound hook) excludes the bot's own rows from re-ingestion, so the provider
    itself needs no bot-user awareness.
    """

    provider_id: str = PROVIDER_ID

    def __init__(
        self,
        *,
        message_sender: IMeinchatMessageSender,
    ) -> None:
        self._message_sender = message_sender
        # Per-chat memory of the last offered choices, for the numbered fallback.
        self._lock = Lock()
        self._last_choices: Dict[Tuple[str, str], List[BotChoice]] = {}

    # ── inbound ───────────────────────────────────────────────────────────────
    def parse_update(self, raw: dict) -> BotInbound:
        """Normalize a meinchat message dict into a neutral :class:`BotInbound`.

        ``raw`` carries ``conversation_id``, ``sender_id`` and ``body`` (the
        plain-path server-readable text). Identity is resolved directly from the
        authenticated sender — no link lookup.
        """
        conversation_id = str(raw.get("conversation_id", ""))
        sender_ref = str(raw.get("sender_id", ""))
        body = raw.get("body")
        chat_ref = ChatRef(provider_id=self.provider_id, chat_id=conversation_id)
        identity = self._identity_for(sender_ref)

        command, args = self._split_command(body)
        # A tapped card arrives as a structured `meta` action — it dispatches
        # the action directly (no number typed). Anything else (absent or
        # malformed meta) falls back to body parsing, exactly as before.
        action_data = self._action_data_from_meta(raw.get("meta"))
        if action_data is None:
            action_data = self._resolve_choice_tap(chat_ref, body)

        return BotInbound(
            provider_id=self.provider_id,
            chat_ref=chat_ref,
            sender_ref=sender_ref,
            text=body,
            command=command,
            args=args,
            action_data=action_data,
            identity=identity,
        )

    def _identity_for(self, sender_ref: str) -> Optional[BotIdentity]:
        """Auto-resolve the authenticated meinchat sender to a vbwd identity."""
        if not sender_ref:
            return None
        try:
            vbwd_user_id = UUID(sender_ref)
        except ValueError:
            return None
        return BotIdentity(
            provider_id=self.provider_id,
            external_user_id=sender_ref,
            vbwd_user_id=vbwd_user_id,
        )

    @staticmethod
    def _action_data_from_meta(meta: Any) -> Optional[str]:
        """Lift ``action_data`` from a ``{"kind":"bot_action", …}`` tap. Returns
        ``None`` for any absent/unknown/malformed ``meta`` so the caller falls
        back to body parsing — never crashes on untrusted input."""
        if not isinstance(meta, dict):
            return None
        if meta.get("kind") != "bot_action":
            return None
        action_data = meta.get("action_data")
        if isinstance(action_data, str) and action_data:
            return action_data
        return None

    @staticmethod
    def _split_command(text: Optional[str]) -> Tuple[Optional[str], List[str]]:
        """Split ``/draw a b`` into ``("draw", ["a", "b"])``; else ``(None, [])``."""
        if not text or not text.startswith("/"):
            return None, []
        parts = text.strip().split()
        return parts[0][1:], parts[1:]

    def _resolve_choice_tap(
        self, chat_ref: ChatRef, body: Optional[str]
    ) -> Optional[str]:
        """A bare 1-based number replying to a numbered menu → its action_data."""
        if not body:
            return None
        stripped = body.strip()
        if not stripped.isdigit():
            return None
        with self._lock:
            choices = self._last_choices.get((chat_ref.provider_id, chat_ref.chat_id))
        if not choices:
            return None
        index = int(stripped) - 1
        if 0 <= index < len(choices):
            return choices[index].action_data
        return None

    def remember_choices(self, chat_ref: ChatRef, choices: List[BotChoice]) -> None:
        """Record (or clear) the choices last offered to a chat for the numbered
        fallback. Called by :meth:`send`; exposed for transport-level tests."""
        key = (chat_ref.provider_id, chat_ref.chat_id)
        with self._lock:
            if choices:
                self._last_choices[key] = list(choices)
            else:
                self._last_choices.pop(key, None)

    # ── outbound ──────────────────────────────────────────────────────────────
    def send(self, reply: BotReply, *, to: ChatRef) -> None:
        """Render ``reply`` as a meinchat message and post it as the bot user.

        Choices ride as structured ``meta`` (rendered as cards by rich clients)
        AND as the numbered-text ``body`` (the universal fallback — a client
        ignoring ``meta`` sees today's menu). Liskov: a non-rich client is
        unchanged.
        """
        body = self._render_body(reply)
        meta = self._build_meta(reply)
        self.remember_choices(to, reply.choices)
        self._message_sender.send_text(
            conversation_id=UUID(to.chat_id),
            body=body,
            protocol_hint=OUTBOUND_PROTOCOL_HINT,
            meta=meta,
        )

    @classmethod
    def _build_meta(cls, reply: BotReply) -> Optional[Dict[str, Any]]:
        """Translate the neutral reply into meinchat's ``message.meta``.

        * choices present → a ``bot_choices`` payload (kind from
          ``reply.meta`` if set, the serialized choices with optional ``hint``,
          and ``reply.meta['text']`` as the clean card prompt when present);
        * no choices but ``reply.meta`` present → that provider-neutral payload
          passes straight through (``bot_cart`` / ``bot_menu`` / ...);
        * otherwise → ``None`` (a plain reply carries no structured meta).

        The numbered-text ``body`` is built independently (the universal
        fallback), so a client ignoring ``meta`` is unaffected — Liskov.
        """
        reply_meta = reply.meta or None
        if reply.choices:
            meta: Dict[str, Any] = {
                "kind": (reply_meta or {}).get("kind", "bot_choices"),
                "choices": cls._serialize_choices(reply.choices),
            }
            if reply_meta and reply_meta.get("text"):
                meta["text"] = reply_meta["text"]
            return meta
        if reply_meta:
            return reply_meta
        return None

    @staticmethod
    def _serialize_choices(choices: List[BotChoice]) -> List[Dict[str, Any]]:
        """Serialize choices, including each optional ``hint`` when present."""
        serialized_choices = []
        for choice in choices:
            entry: Dict[str, Any] = {
                "label": choice.label,
                "action_data": choice.action_data,
            }
            hint = getattr(choice, "hint", None)
            if hint:
                entry["hint"] = hint
            serialized_choices.append(entry)
        return serialized_choices

    @staticmethod
    def _render_body(reply: BotReply) -> str:
        """Append ``reply.choices`` as a numbered menu (meinchat plain fallback)."""
        if not reply.choices:
            return reply.text
        lines = [reply.text, ""]
        for position, choice in enumerate(reply.choices, start=1):
            lines.append(f"{position}. {choice.label}")
        lines.append("")
        lines.append("Reply with the number of your choice.")
        return "\n".join(lines)

    # ── linking ───────────────────────────────────────────────────────────────
    def build_link_deeplink(self, token: str) -> Optional[str]:
        """No linking — meinchat identity is auth-native, so always ``None``."""
        return None
