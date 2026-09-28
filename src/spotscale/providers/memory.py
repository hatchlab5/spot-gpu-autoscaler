"""An in-memory provider that simulates a fleet.

Ships in the box so the loops are runnable and testable without any cloud
account. The `set_status` / `set_uptime` helpers let a test drive instances into
states a real provider would report (e.g. 'exited').
"""

from __future__ import annotations

from dataclasses import replace
from typing import List

from ..models import Instance
from .base import Provider, ProviderError


class MemoryProvider(Provider):
    name = "memory"

    def __init__(self, default_gpu: str = "RTX_3090", default_price: float = 0.30):
        self._instances: dict[str, Instance] = {}
        self._counter = 0
        self.default_gpu = default_gpu
        self.default_price = default_price

    def spin(self, gpu: str, max_price: float, label: str = "") -> Instance:
        # The offer price is what the provider charges; we do NOT get to clamp
        # it down to our ceiling. Refuse if the cheapest offer is over budget.
        price = self.default_price
        if price <= 0 or price > max_price:
            raise ProviderError(
                f"no offer for {gpu!r} at or below ${max_price:.4f}/hr"
            )
        self._counter += 1
        iid = f"mem-{self._counter}"
        inst = Instance(
            id=iid,
            status="running",
            gpu=gpu or self.default_gpu,
            price_per_hour=price,
            label=label,
            uptime_hours=0.0,
        )
        self._instances[iid] = inst
        return replace(inst)

    def list(self) -> List[Instance]:
        # Return copies so callers can't mutate internal state.
        return [replace(i) for i in self._instances.values()]

    def kill(self, instance_id: str) -> bool:
        return self._instances.pop(instance_id, None) is not None

    # --- simulation helpers (not part of the Provider contract) ---
    def set_status(self, instance_id: str, status: str) -> None:
        if instance_id in self._instances:
            self._instances[instance_id].status = status

    def set_uptime(self, instance_id: str, hours: float) -> None:
        if instance_id in self._instances:
            self._instances[instance_id].uptime_hours = hours

    def set_price(self, instance_id: str, price: float) -> None:
        if instance_id in self._instances:
            self._instances[instance_id].price_per_hour = price

