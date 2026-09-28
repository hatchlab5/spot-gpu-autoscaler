"""StateBackend interface + shared convenience methods.

A backend stores WorkerRecords keyed by worker_id. Subclasses implement five
primitives; everything else (filtering, cost summation) is built on top.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import (
    ACTIVE_STATUSES,
    UPDATABLE_FIELDS,
    WorkerRecord,
    status_values,
)


class StateBackend(ABC):
    # --- primitives ---
    @abstractmethod
    def add(self, record: WorkerRecord) -> None:
        ...

    @abstractmethod
    def get(self, worker_id: str) -> Optional[WorkerRecord]:
        ...

    @abstractmethod
    def update(self, worker_id: str, **fields) -> None:
        """Update whitelisted fields. Unknown fields raise KeyError."""

    @abstractmethod
    def remove(self, worker_id: str) -> None:
        ...

    @abstractmethod
    def all(self) -> List[WorkerRecord]:
        ...

    # --- shared helpers ---
    @staticmethod
    def _validate_fields(fields: dict) -> None:
        bad = set(fields) - UPDATABLE_FIELDS
        if bad:
            raise KeyError(f"not updatable: {sorted(bad)}")

    def list(self, statuses=None) -> List[WorkerRecord]:
        recs = self.all()
        if statuses is None:
            return recs
        wanted = status_values(statuses)
        return [r for r in recs if r.status in wanted]

    def total_hourly_cost(self, statuses=ACTIVE_STATUSES) -> float:
        return round(sum(r.hourly_cost for r in self.list(statuses)), 4)

