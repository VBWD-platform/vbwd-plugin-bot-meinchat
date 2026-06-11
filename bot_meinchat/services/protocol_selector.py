"""Adaptive plain/e2e protocol selection (S45.5).

The bot-meinchat adapter does not hard-import meinchat-plus. It detects the E2E
capability the same way meinchat itself does — by resolving the registered
``IDeviceDirectory`` and asking whether it is the meinchat-alone
``NullDeviceDirectory`` (no device keys) or a real meinchat-plus directory.

- ``NullDeviceDirectory`` / nothing registered → ``plain``: the bot reads the
  server-readable ``body`` and replies plain.
- A real directory (meinchat-plus enabled) → ``e2e_v1``: the bot would act as an
  E2E participant. (See the module note in the protocol-selection spec — the
  server-side decrypt half of the e2e path is flagged as 45.5.1; this module is
  the single detection point so the rest of the adapter never duplicates it.)
"""
from __future__ import annotations

from typing import Type, cast

from plugins.meinchat.meinchat.extensibility import registry
from plugins.meinchat.meinchat.extensibility.identity import (
    IDeviceDirectory,
    NullDeviceDirectory,
)

BOT_PROTOCOL_PLAIN = "plain"
BOT_PROTOCOL_E2E = "e2e_v1"


def select_bot_protocol() -> str:
    """Return the protocol the bot conversation uses, adaptively.

    ``plain`` unless a real (non-null) device directory is registered, in which
    case meinchat-plus is enabled and the conversation is end-to-end encrypted.
    """
    try:
        directory = registry.resolve_first(cast("Type[IDeviceDirectory]", IDeviceDirectory))
    except LookupError:
        return BOT_PROTOCOL_PLAIN
    if isinstance(directory, NullDeviceDirectory):
        return BOT_PROTOCOL_PLAIN
    return BOT_PROTOCOL_E2E
