"""Core data types shared across providers, state backends, and the loops."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


class InstanceStatus(str, enum.Enum):
    """Lifecycle of a worker as tracked in our state.

    The last two are *provider-reported* terminal states that, on spot markets,
    keep billing until the instance is destroyed. The reaper hunts exactly these.
    """

    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    EXITED = "exited"
    OFFLINE = "offline"


# Statuses that represent live, billable capacity we are responsible for.
ACTIVE_STATUSES = frozenset(
    {InstanceStatus.STARTING, InstanceStatus.RUNNING, InstanceStatus.IDLE}
)

# Terminal-but-still-billing states the reaper destroys. A live worker is never
# in one of these, so reaping them can never kill useful work.
DEAD_BILLABLE_STATUSES = frozenset({InstanceStatus.EXITED, InstanceStatus.OFFLINE})


def status_values(statuses) -> set:
    """Normalize an iterable of InstanceStatus | str to a set of raw string values."""
    out = set()
    for s in statuses:
        out.add(s.value if isinstance(s, InstanceStatus) else str(s))
    return out


@dataclass
class Instance:
    """A provider-level instance, as returned by Provider.list()/spin().

    `status` is the provider's raw status, lower-cased. It is deliberately a plain
    string (not the enum) because providers report states we don't model.
    """

    id: str
    status: str = ""
    gpu: str = ""
    price_per_hour: float = 0.0
    label: str = ""
    uptime_hours: float = 0.0
    ip: str = ""


@dataclass
class WorkerRecord:
    """A worker WE provisioned, as tracked in a StateBackend.

    Timestamps are epoch seconds (float) so backends stay simple and portable.
    """

    worker_id: str
    provider: str
    instance_id: Optional[str] = None
    status: str = InstanceStatus.STARTING.value
    gpu: str = ""
    hourly_cost: float = 0.0
    started_at: float = 0.0
    last_heartbeat: Optional[float] = None
    idle_since: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "worker_id": self.worker_id,
            "provider": self.provider,
            "instance_id": self.instance_id,
            "status": self.status,
            "gpu": self.gpu,
            "hourly_cost": self.hourly_cost,
            "started_at": self.started_at,
            "last_heartbeat": self.last_heartbeat,
            "idle_since": self.idle_since,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkerRecord":
        return cls(
            worker_id=d["worker_id"],
            provider=d.get("provider", ""),
            instance_id=d.get("instance_id"),
            status=d.get("status", InstanceStatus.STARTING.value),
            gpu=d.get("gpu", ""),
            hourly_cost=float(d.get("hourly_cost", 0.0) or 0.0),
            started_at=float(d.get("started_at", 0.0) or 0.0),
            last_heartbeat=d.get("last_heartbeat"),
            idle_since=d.get("idle_since"),
        )


# Fields a StateBackend.update() is allowed to write. Guards against typos and
# arbitrary column injection in the SQL backend.
UPDATABLE_FIELDS = frozenset(
    {
        "instance_id",
        "status",
        "gpu",
        "hourly_cost",
        "last_heartbeat",
        "idle_since",
    }
)

