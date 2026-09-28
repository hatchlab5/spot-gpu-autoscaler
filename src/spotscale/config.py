"""Configuration object. Plain dataclass; `from_env()` reads SPOTSCALE_* vars.

There is deliberately no import-time config loading and no global settings
singleton — construct a Config and pass it in.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    # What to rent
    gpu: str = "RTX_3090"
    max_price_per_hour: float = 0.60          # per single instance
    worker_image: str = "pytorch/pytorch:latest"

    # Fleet-wide hard ceiling
    max_hourly_spend: float = 5.00

    # Fleet size bounds
    min_workers: int = 0
    max_workers: int = 4

    # Scaling behaviour
    scale_threshold: int = 10                 # pending items per worker before scale-up
    idle_teardown_s: int = 600                # idle this long -> tear down
    stale_heartbeat_s: int = 300              # heartbeat older than this -> dead
    starting_timeout_s: int = 900             # stuck in 'starting' this long -> failed
    scale_interval_s: int = 30                # autoscale loop period
    retention_s: int = 7 * 24 * 3600          # purge terminal records older than this

    # Reaper
    reaper_interval_s: int = 600
    reaper_alert_threshold: int = 5           # reap >= this in one pass -> alert

    # Worker id prefix (also used as provider label prefix)
    worker_prefix: str = "spot"

    def __post_init__(self) -> None:
        """Validate the config so a nonsensical fleet can't be constructed."""
        if self.min_workers < 0:
            raise ValueError(f"min_workers must be >= 0, got {self.min_workers}")
        if self.max_workers < 0:
            raise ValueError(f"max_workers must be >= 0, got {self.max_workers}")
        if self.min_workers > self.max_workers:
            raise ValueError(
                f"min_workers ({self.min_workers}) must be <= "
                f"max_workers ({self.max_workers})"
            )
        if self.max_hourly_spend <= 0:
            raise ValueError(
                f"max_hourly_spend must be > 0, got {self.max_hourly_spend}"
            )
        if self.max_price_per_hour < 0:
            raise ValueError(
                f"max_price_per_hour must be >= 0, got {self.max_price_per_hour}"
            )

    @classmethod
    def from_env(cls, environ: dict = None, prefix: str = "SPOTSCALE_") -> "Config":
        env = environ if environ is not None else os.environ
        d = cls()

        def get(name, cast, default):
            raw = env.get(prefix + name)
            if raw is None or raw == "":
                return default
            try:
                return cast(raw)
            except (ValueError, TypeError):
                return default

        return cls(
            gpu=get("GPU", str, d.gpu),
            max_price_per_hour=get("MAX_PRICE", float, d.max_price_per_hour),
            worker_image=get("WORKER_IMAGE", str, d.worker_image),
            max_hourly_spend=get("MAX_SPEND", float, d.max_hourly_spend),
            min_workers=get("MIN_WORKERS", int, d.min_workers),
            max_workers=get("MAX_WORKERS", int, d.max_workers),
            scale_threshold=get("SCALE_THRESHOLD", int, d.scale_threshold),
            idle_teardown_s=get("IDLE_TEARDOWN_S", int, d.idle_teardown_s),
            stale_heartbeat_s=get("STALE_HEARTBEAT_S", int, d.stale_heartbeat_s),
            starting_timeout_s=get("STARTING_TIMEOUT_S", int, d.starting_timeout_s),
            scale_interval_s=get("SCALE_INTERVAL_S", int, d.scale_interval_s),
            retention_s=get("RETENTION_S", int, d.retention_s),
            reaper_interval_s=get("REAPER_INTERVAL_S", int, d.reaper_interval_s),
            reaper_alert_threshold=get(
                "REAPER_ALERT_THRESHOLD", int, d.reaper_alert_threshold
            ),
            worker_prefix=get("WORKER_PREFIX", str, d.worker_prefix),
        )

