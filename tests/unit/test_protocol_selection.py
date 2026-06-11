"""Unit specs for the adaptive plain/e2e selection seam.

The adapter chooses its protocol from *whether meinchat-plus is enabled* — i.e.
whether a real (non-null) ``IDeviceDirectory`` is registered — never from a hard
import of meinchat-plus. ``select_bot_protocol`` is the single detection point.

NOTE (scope guard, S45.5): the *plain* branch is the deliverable this
sub-sprint. The *e2e* branch is selected when a real directory is present, but a
true server-side decrypt of the opaque envelope needs meinchat-plus to expose a
bot-device private-key + decrypt API that does not yet exist (its codec holds no
keys and ``decode`` raises ``NotImplementedError`` for ``e2e_v1``). The remaining
plus/fe wiring is flagged as **45.5.1**; this test asserts only the *selection*.
"""
from typing import List
from uuid import UUID, uuid4

from plugins.meinchat.meinchat.extensibility import registry
from plugins.meinchat.meinchat.extensibility.identity import (
    Device,
    IDeviceDirectory,
    NullDeviceDirectory,
)
from plugins.bot_meinchat.bot_meinchat.services.protocol_selector import (
    BOT_PROTOCOL_E2E,
    BOT_PROTOCOL_PLAIN,
    select_bot_protocol,
)


class _FakeDeviceDirectory:
    """A non-null IDeviceDirectory standing in for meinchat-plus."""

    def register(self, user_id, pubkey, alg, label=None) -> Device:
        return Device(id=uuid4(), user_id=user_id, pubkey=pubkey, alg=alg, label=label)

    def lookup_active(self, user_id: UUID) -> List[Device]:
        return []

    def revoke(self, device_id: UUID) -> None:
        return None

    def has_any(self, user_id: UUID) -> bool:
        return True


def teardown_function(_):
    registry.reset_for_tests(IDeviceDirectory)


def test_plain_selected_when_no_directory_registered():
    registry.reset_for_tests(IDeviceDirectory)
    assert select_bot_protocol() == BOT_PROTOCOL_PLAIN


def test_plain_selected_with_null_directory():
    registry.reset_for_tests(IDeviceDirectory)
    registry.register(IDeviceDirectory, NullDeviceDirectory())
    assert select_bot_protocol() == BOT_PROTOCOL_PLAIN


def test_e2e_selected_when_real_directory_registered():
    registry.reset_for_tests(IDeviceDirectory)
    registry.register(IDeviceDirectory, _FakeDeviceDirectory())
    assert select_bot_protocol() == BOT_PROTOCOL_E2E
