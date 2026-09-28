"""The autoscaler: match capacity to a pending-work signal, tear down idle.

Also owns worker health: it reaps workers whose heartbeat went stale and workers
stuck in 'starting' that never reported in — both of which would otherwise be
silent orphans.

Time is injectable (`now_fn`) so the whole thing is deterministically testable.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Callable, Optional

from .config import Config
from .costguard import CostGuard
from .models import (
    ACTIVE_STATUSES,
    InstanceStatus,
    WorkerRecord,
)
from .providers.base import Provider, ProviderError
from .state.base import StateBackend

logger = logging.getLogger("spotscale.autoscaler")

_S = InstanceStatus


class AutoScaler:
    def __init__(
        self,
        provider: Provider,
        state: StateBackend,
        config: Config,
        demand_fn: Callable[[], int],
        cost_guard: Optional[CostGuard] = None,
        now_fn: Callable[[], float] = time.time,
        logger_: Optional[logging.Logger] = None,
    ):
        self.provider = provider
        self.state = state
        self.config = config
        self.demand_fn = demand_fn
        self.cost_guard = cost_guard
        self.now = now_fn
        self.log = logger_ or logger

    # ------------------------------------------------------------------ #
    # Public: heartbeat reporting from workers
    # ------------------------------------------------------------------ #
    def report_heartbeat(self, worker_id: str, busy: bool) -> None:
        """A worker checks in. `busy=False` starts (or continues) its idle timer."""
        rec = self.state.get(worker_id)
        if rec is None:
            return
        now = self.now()
        if rec.status in (
            _S.STOPPING.value,
            _S.STOPPED.value,
            _S.FAILED.value,
        ):
            return  # don't resurrect a terminal worker
        if busy:
            self.state.update(
                worker_id, status=_S.RUNNING.value, last_heartbeat=now, idle_since=None
            )
        else:
            idle_since = rec.idle_since or now
            self.state.update(
                worker_id, status=_S.IDLE.value, last_heartbeat=now, idle_since=idle_since
            )

    # ------------------------------------------------------------------ #
    # The tick
    # ------------------------------------------------------------------ #
    def tick(self, dry_run: bool = False) -> None:
        self._reap_stale(dry_run)
        self._reap_stuck_starting(dry_run)
        self._purge_terminal()
        demand = max(0, int(self.demand_fn()))
        self._scale(demand, dry_run)

    def _active(self):
        return self.state.list(ACTIVE_STATUSES)

    def _scale(self, demand: int, dry_run: bool) -> None:
        cfg = self.config
        active = self._active()
        total = len(active)
        self.log.info(
            "scale: demand=%d active=%d min=%d max=%d",
            demand,
            total,
            cfg.min_workers,
            cfg.max_workers,
        )

        # Always float up to the floor.
        if total < cfg.min_workers:
            for _ in range(cfg.min_workers - total):
                self._provision(dry_run)
            return

        if demand == 0:
            self._scale_down_idle(active, dry_run)
            return

        # demand > 0
        if total == 0:
            self._provision(dry_run)
            return

        if demand >= cfg.scale_threshold * total and total < cfg.max_workers:
            self._provision(dry_run)

    def _scale_down_idle(self, active, dry_run: bool) -> None:
        cfg = self.config
        total = len(active)
        if total <= cfg.min_workers:
            return
        now = self.now()
        idle = [
            r
            for r in active
            if r.status == _S.IDLE.value
            and r.idle_since is not None
            and (now - r.idle_since) > cfg.idle_teardown_s
        ]
        removable = total - cfg.min_workers
        for rec in idle[:removable]:
            self.log.info("scaling down idle worker %s", rec.worker_id)
            self._deprovision(rec.worker_id, dry_run)

    # ------------------------------------------------------------------ #
    # Provision / deprovision
    # ------------------------------------------------------------------ #
    def _provision(self, dry_run: bool) -> Optional[str]:
        cfg = self.config
        if len(self._active()) >= cfg.max_workers:
            self.log.debug("at max_workers (%d), not provisioning", cfg.max_workers)
            return None

        if self.cost_guard is not None and not self.cost_guard.can_provision(
            cfg.max_price_per_hour
        ):
            self.log.warning("cost cap blocks provisioning")
            return None

        worker_id = f"{cfg.worker_prefix}-{uuid.uuid4().hex[:12]}"

        if dry_run:
            self.log.info("[dry-run] would provision %s", worker_id)
            return worker_id

        rec = WorkerRecord(
            worker_id=worker_id,
            provider=self.provider.name,
            status=_S.STARTING.value,
            started_at=self.now(),
        )
        self.state.add(rec)
        try:
            inst = self.provider.spin(cfg.gpu, cfg.max_price_per_hour, label=worker_id)
        except ProviderError as e:
            self.log.error("provision failed for %s: %s", worker_id, e)
            self.state.update(worker_id, status=_S.FAILED.value)
            return None

        self.state.update(
            worker_id,
            instance_id=inst.id,
            hourly_cost=inst.price_per_hour,
            gpu=inst.gpu,
        )
        self.log.info(
            "provisioned %s -> instance %s (%s, $%.4f/hr)",
            worker_id,
            inst.id,
            inst.gpu,
            inst.price_per_hour,
        )
        return worker_id

    def _deprovision(self, worker_id: str, dry_run: bool, final_status: str = None) -> None:
        rec = self.state.get(worker_id)
        if rec is None:
            return
        final_status = final_status or _S.STOPPED.value
        if dry_run:
            self.log.info("[dry-run] would deprovision %s", worker_id)
            return
        self.state.update(worker_id, status=_S.STOPPING.value)
        if rec.instance_id:
            try:
                self.provider.kill(rec.instance_id)
            except ProviderError as e:
                self.log.error("kill failed for %s (%s): %s", worker_id, rec.instance_id, e)
        self.state.update(worker_id, status=final_status)

    # ------------------------------------------------------------------ #
    # Health reaping
    # ------------------------------------------------------------------ #
    def _reap_stale(self, dry_run: bool) -> None:
        cfg = self.config
        now = self.now()
        for rec in self.state.list((_S.RUNNING, _S.IDLE)):
            hb = rec.last_heartbeat
            stale = (hb is not None and (now - hb) > cfg.stale_heartbeat_s) or (
                hb is None and (now - rec.started_at) > cfg.stale_heartbeat_s
            )
            if stale:
                self.log.warning("worker %s stale (no heartbeat) — reaping", rec.worker_id)
                self._deprovision(rec.worker_id, dry_run, final_status=_S.FAILED.value)

    def _reap_stuck_starting(self, dry_run: bool) -> None:
        cfg = self.config
        now = self.now()
        for rec in self.state.list((_S.STARTING,)):
            if rec.last_heartbeat is None and (now - rec.started_at) > cfg.starting_timeout_s:
                self.log.warning(
                    "worker %s stuck in 'starting' > %ds — failing",
                    rec.worker_id,
                    cfg.starting_timeout_s,
                )
                self._deprovision(rec.worker_id, dry_run, final_status=_S.FAILED.value)

    def _purge_terminal(self) -> None:
        """Drop old terminal records so state doesn't grow without bound."""
        now = self.now()
        for rec in self.state.list((_S.STOPPED, _S.FAILED)):
            # failed provisions (never got an instance) go immediately;
            # others age out by retention.
            if rec.instance_id is None or (now - rec.started_at) > self.config.retention_s:
                self.state.remove(rec.worker_id)


def run_loop(
    scaler: AutoScaler,
    interval_s: int,
    stop: Optional[Callable[[], bool]] = None,
    sleep: Callable[[float], None] = None,
    dry_run: bool = False,
) -> None:
    sleep = sleep or time.sleep
    stop = stop or (lambda: False)
    while not stop():
        try:
            scaler.tick(dry_run=dry_run)
        except Exception as e:  # a loop must not die on one bad tick
            scaler.log.error("tick failed: %s", e, exc_info=True)
        sleep(interval_s)

