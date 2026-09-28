"""The hard $/hr spend cap.

Two jobs:
  1. `can_provision()` — refuse a new instance that would push live spend over cap.
  2. `enforce()`       — a backstop that KILLS over-cap when live spend is already
                         above the ceiling (drift, manual launch, price change).

Spend is measured from the PROVIDER's live view, not from our state, because the
provider is the thing that actually bills. On spot markets even exited/offline
instances bill until destroyed, so every listed instance is counted as billable.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from .providers.base import Provider, ProviderError

logger = logging.getLogger("spotscale.costguard")


class CostCapExceeded(Exception):
    """Raised by guard() when spend is over cap and callers asked to hard-fail."""


class CostGuard:
    def __init__(
        self,
        provider: Provider,
        max_hourly_spend: float,
        logger_: Optional[logging.Logger] = None,
    ):
        self.provider = provider
        self.max_hourly_spend = float(max_hourly_spend)
        self.log = logger_ or logger

    def current_spend(self) -> float:
        """Live $/hr across every instance the provider reports."""
        try:
            instances = self.provider.list()
        except ProviderError as e:
            # If we can't read spend, fail SAFE: report the cap so callers refuse
            # to provision more. Better to under-provision than to blow the budget
            # blind.
            self.log.warning("cost read failed, assuming at cap: %s", e)
            return self.max_hourly_spend
        return round(sum(i.price_per_hour for i in instances), 4)

    def can_provision(self, estimated_hourly: float) -> bool:
        """True if adding an instance at `estimated_hourly` stays within cap."""
        spend = self.current_spend()
        ok = (spend + float(estimated_hourly)) <= self.max_hourly_spend
        if not ok:
            self.log.warning(
                "cost cap would be exceeded: live $%.4f/hr + $%.4f/hr > cap $%.4f/hr",
                spend,
                estimated_hourly,
                self.max_hourly_spend,
            )
        return ok

    def enforce(self, dry_run: bool = False) -> List[str]:
        """Kill freshest-first until live spend is back under the cap.

        Freshest-first (lowest uptime) minimizes work lost — a brand-new instance
        has done the least. Returns the ids killed (or that would be killed).
        """
        try:
            instances = self.provider.list()
        except ProviderError as e:
            self.log.error("cost enforce could not list instances: %s", e)
            return []

        total = round(sum(i.price_per_hour for i in instances), 4)
        if total <= self.max_hourly_spend:
            return []

        self.log.warning(
            "OVER CAP: live $%.4f/hr > cap $%.4f/hr — enforcing", total, self.max_hourly_spend
        )
        killed: List[str] = []
        for inst in sorted(instances, key=lambda i: i.uptime_hours):
            if total <= self.max_hourly_spend:
                break
            if dry_run:
                self.log.info("[dry-run] would kill %s ($%.4f/hr)", inst.id, inst.price_per_hour)
                killed.append(inst.id)
                total = round(total - inst.price_per_hour, 4)
                continue
            try:
                if self.provider.kill(inst.id):
                    killed.append(inst.id)
                    total = round(total - inst.price_per_hour, 4)
                    self.log.warning(
                        "killed %s ($%.4f/hr) to enforce cap; live now $%.4f/hr",
                        inst.id,
                        inst.price_per_hour,
                        total,
                    )
            except ProviderError as e:
                self.log.error("failed to kill %s during enforce: %s", inst.id, e)
        return killed

    def guard(self, estimated_hourly: float) -> None:
        """Raise CostCapExceeded if provisioning would break the cap."""
        if not self.can_provision(estimated_hourly):
            raise CostCapExceeded(
                f"live spend + ${estimated_hourly:.4f}/hr exceeds cap "
                f"${self.max_hourly_spend:.4f}/hr"
            )


def run_loop(
    guard: CostGuard,
    interval_s: int,
    stop: Optional[Callable[[], bool]] = None,
    sleep: Callable[[float], None] = None,
    dry_run: bool = False,
) -> None:
    import time as _time

    sleep = sleep or _time.sleep
    stop = stop or (lambda: False)
    while not stop():
        guard.enforce(dry_run=dry_run)
        sleep(interval_s)

