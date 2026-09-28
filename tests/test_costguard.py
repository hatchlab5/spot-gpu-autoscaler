from spotscale.costguard import CostCapExceeded, CostGuard
from spotscale.providers.memory import MemoryProvider
import pytest


def test_can_provision_under_cap():
    p = MemoryProvider(default_price=0.30)
    guard = CostGuard(p, max_hourly_spend=1.00)
    assert guard.can_provision(0.30) is True


def test_can_provision_blocked_over_cap():
    p = MemoryProvider(default_price=0.40)
    p.spin("RTX_3090", 0.60)
    p.spin("RTX_3090", 0.60)  # live spend now 0.80
    guard = CostGuard(p, max_hourly_spend=1.00)
    assert guard.can_provision(0.40) is False  # 0.80 + 0.40 > 1.00
    assert guard.can_provision(0.20) is True   # 0.80 + 0.20 == 1.00


def test_guard_raises():
    p = MemoryProvider(default_price=0.60)
    p.spin("RTX_3090", 0.60)  # 0.60
    guard = CostGuard(p, max_hourly_spend=1.00)
    with pytest.raises(CostCapExceeded):
        guard.guard(0.60)  # 1.20 > 1.00


def test_enforce_kills_freshest_first_until_under_cap():
    p = MemoryProvider(default_price=0.50)
    a = p.spin("RTX_3090", 0.60)
    b = p.spin("RTX_3090", 0.60)
    c = p.spin("RTX_3090", 0.60)  # live spend 1.50, cap 1.00
    # make 'a' oldest, 'c' freshest
    p.set_uptime(a.id, 10.0)
    p.set_uptime(b.id, 5.0)
    p.set_uptime(c.id, 0.5)
    guard = CostGuard(p, max_hourly_spend=1.00)
    killed = guard.enforce()
    # freshest (c) killed first; that alone brings 1.50 -> 1.00, so only one kill
    assert killed == [c.id]
    assert guard.current_spend() == 1.00


def test_enforce_noop_when_under_cap():
    p = MemoryProvider(default_price=0.30)
    p.spin("RTX_3090", 0.60)
    guard = CostGuard(p, max_hourly_spend=1.00)
    assert guard.enforce() == []


def test_enforce_dry_run_kills_nothing():
    p = MemoryProvider(default_price=0.60)
    p.spin("RTX_3090", 0.60)
    p.spin("RTX_3090", 0.60)  # 1.20 over 1.00
    guard = CostGuard(p, max_hourly_spend=1.00)
    would = guard.enforce(dry_run=True)
    assert len(would) >= 1
    assert len(p.list()) == 2  # nothing actually killed



# --- fail-safe: the headline guarantee is that when provider spend CANNOT be
# read, the cost cap refuses to provision rather than blowing the budget blind,
# and the out-of-band killers degrade to a no-op instead of crashing. ---

from spotscale.providers.base import Provider, ProviderError
from spotscale.reaper import Reaper


class UnreadableProvider(Provider):
    """A provider whose list() always fails — simulates an API/auth/network
    outage at the exact moment we need to read spend."""

    name = "unreadable"

    def spin(self, gpu, max_price, label=""):
        raise ProviderError("cannot spin: provider unreadable")

    def list(self):
        raise ProviderError("cannot read instances: provider unreadable")

    def kill(self, instance_id):
        raise ProviderError("cannot kill: provider unreadable")


def test_current_spend_returns_cap_when_unreadable():
    guard = CostGuard(UnreadableProvider(), max_hourly_spend=3.00)
    # Can't read spend -> assume we're already at the cap (fail safe).
    assert guard.current_spend() == 3.00


def test_can_provision_false_when_unreadable():
    guard = CostGuard(UnreadableProvider(), max_hourly_spend=3.00)
    # At-cap + any positive estimate -> refuse.
    assert guard.can_provision(0.01) is False
    # Even a zero-cost add is only exactly at cap, never under it -> still refuse
    # anything that would grow the fleet.
    assert guard.can_provision(0.30) is False


def test_enforce_returns_empty_and_does_not_crash_when_unreadable():
    guard = CostGuard(UnreadableProvider(), max_hourly_spend=3.00)
    # Can't list -> nothing to enforce against; must not raise.
    assert guard.enforce() == []
    assert guard.enforce(dry_run=True) == []


def test_reaper_returns_empty_and_does_not_crash_when_unreadable():
    reaper = Reaper(UnreadableProvider())
    # Can't list -> no orphans reaped; must not raise.
    assert reaper.reap() == []
    assert reaper.reap(dry_run=True) == []
