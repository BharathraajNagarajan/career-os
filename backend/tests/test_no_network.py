import contextlib
import socket

import pytest

from tests.conftest import NetworkAccessBlocked


def test_outbound_connections_are_blocked_during_tests() -> None:
    with socket.socket() as probe, pytest.raises(NetworkAccessBlocked):
        probe.connect(("93.184.216.34", 443))


def test_hostnames_that_are_not_loopback_are_blocked() -> None:
    with socket.socket() as probe, pytest.raises(NetworkAccessBlocked):
        probe.connect(("api.anthropic.com", 443))


def test_loopback_stays_reachable_for_the_database() -> None:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        with contextlib.suppress(OSError):
            probe.connect(("127.0.0.1", 9))
