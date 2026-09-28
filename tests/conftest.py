"""Shared test fixtures/helpers. No network, no real cloud accounts."""

from __future__ import annotations

import pytest

from spotscale.config import Config
from spotscale.providers.memory import MemoryProvider
from spotscale.state import get_state


class Clock:
    """A controllable clock for deterministic time-based tests."""

    def __init__(self, t: float = 1000.0):
        self.t = float(t)

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def provider():
    return MemoryProvider(default_gpu="RTX_3090", default_price=0.30)


@pytest.fixture(params=["json", "sqlite"])
def state(request, tmp_path):
    kind = request.param
    path = str(tmp_path / ("state.json" if kind == "json" else "state.db"))
    return get_state(kind, path)


@pytest.fixture
def config():
    return Config(
        gpu="RTX_3090",
        max_price_per_hour=0.60,
        max_hourly_spend=1.00,
        min_workers=0,
        max_workers=3,
        scale_threshold=10,
        idle_teardown_s=600,
        stale_heartbeat_s=300,
        starting_timeout_s=900,
    )

