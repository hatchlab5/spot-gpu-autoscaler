"""The out-of-band orphan reaper.

Destroys instances in a terminal-but-still-billing state (exited/offline). It
depends on NOTHING but the provider API — no state file, no database, no app —
so it keeps working when everything else is down or you're locked out of the
box that provisioned the instances. That independence is the whole point: the
thing that stops the bleeding must not depend on the thing that caused it.

If it reaps a lot in one pass, that means your in-app teardown is still leaking —
so it can raise an alert via an injected callback.
"""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional

from .models import DEAD_BILLABLE_STATUSES, status_values
from .providers.base import Provider, ProviderError

logger = logging.getLogger("spotscale.reaper")

_DEAD = status_values(DEAD_BILLABLE_STATUSES)


class Reaper:
    def __init__(
        self,
        provider: Provider,
        alert_threshold: int = 5,
        alert_fn: Optional[Callable[[int, List[str]], None]] = None,
        label_prefix: Optional[str] = None,
        logger_: Optional[logging.Logger] = None,
    ):
        self.provider = provider
        self.alert_threshold = alert_threshold
        self.alert_fn = alert_fn
        self.label_prefix = label_prefix
        self.log = logger_ or logger

    def find_orphans(self):
        instances = self.provider.list()
        orphans = [i for i in instances if i.status.lower() in _DEAD]
        if self.label_prefix:
            orphans = [i for i in orphans if (i.label or "").startswith(self.label_prefix)]
        return orphans

    def reap(self, dry_run: bool = False) -> List[str]:
        try:
            orphans = self.find_orphans()
        except ProviderError as e:
            self.log.error("reaper could not list instances: %s", e)
            return []

        if not orphans:
            self.log.info("clean: no orphaned (exited/offline) instances")
            return []

        reaped: List[str] = []
        for inst in orphans:
            if dry_run:
                self.log.info(
                    "[dry-run] would reap %s (%s, $%.4f/hr)",
                    inst.id,
                    inst.status,
                    inst.price_per_hour,
                )
                reaped.append(inst.id)
                continue
            try:
                if self.provider.kill(inst.id):
                    self.log.warning("reaped %s (%s, $%.4f/hr)", inst.id, inst.status, inst.price_per_hour)
                    reaped.append(inst.id)
                else:
                    self.log.error("kill returned false for %s", inst.id)
            except ProviderError as e:
                self.log.error("failed to reap %s: %s", inst.id, e)

        if len(reaped) >= self.alert_threshold:
            self.log.warning(
                "reaped %d orphans in one pass — in-app teardown is likely still leaking",
                len(reaped),
            )
            if self.alert_fn:
                try:
                    self.alert_fn(len(reaped), reaped)
                except Exception as e:  # an alert failure must never crash the reaper
                    self.log.error("alert hook failed: %s", e)
        return reaped


def run_loop(
    reaper: Reaper,
    interval_s: int,
    stop: Optional[Callable[[], bool]] = None,
    sleep: Callable[[float], None] = None,
    dry_run: bool = False,
) -> None:
    sleep = sleep or time.sleep
    stop = stop or (lambda: False)
    while not stop():
        reaper.reap(dry_run=dry_run)
        sleep(interval_s)

