import pytest

from spotscale.providers.base import ProviderError
from spotscale.providers.memory import MemoryProvider


def test_spin_list_kill():
    p = MemoryProvider(default_price=0.30)
    inst = p.spin("RTX_3090", max_price=0.60, label="w1")
    assert inst.id
    assert inst.gpu == "RTX_3090"
    assert inst.price_per_hour == 0.30
    assert inst.label == "w1"

    listed = p.list()
    assert len(listed) == 1
    assert listed[0].id == inst.id

    assert p.kill(inst.id) is True
    assert p.list() == []
    assert p.kill(inst.id) is False  # already gone


def test_spin_refuses_over_price():
    p = MemoryProvider(default_price=0.90)
    with pytest.raises(ProviderError):
        p.spin("RTX_3090", max_price=0.50)


def test_list_returns_copies():
    p = MemoryProvider()
    inst = p.spin("RTX_3090", 0.60)
    got = p.list()[0]
    got.status = "mutated"
    # internal state unaffected
    assert p.list()[0].status == "running"


def test_simulation_helpers():
    p = MemoryProvider()
    inst = p.spin("RTX_3090", 0.60)
    p.set_status(inst.id, "exited")
    p.set_uptime(inst.id, 42.0)
    got = p.list()[0]
    assert got.status == "exited"
    assert got.uptime_hours == 42.0

