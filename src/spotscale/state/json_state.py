"""JSON file state backend. Single file, whole-file rewrite, process-lock.

Fine for a single autoscaler process. For multi-writer setups use the SQLite
backend (or your own).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import List, Optional

from ..models import WorkerRecord
from .base import StateBackend


class JsonStateBackend(StateBackend):
    def __init__(self, path: str):
        self.path = str(path)
        self._lock = threading.RLock()
        if not os.path.exists(self.path):
            self._write({})

    def _read(self) -> dict:
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".spotscale-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)  # atomic
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, record: WorkerRecord) -> None:
        with self._lock:
            data = self._read()
            data[record.worker_id] = record.to_dict()
            self._write(data)

    def get(self, worker_id: str) -> Optional[WorkerRecord]:
        with self._lock:
            d = self._read().get(worker_id)
            return WorkerRecord.from_dict(d) if d else None

    def update(self, worker_id: str, **fields) -> None:
        self._validate_fields(fields)
        with self._lock:
            data = self._read()
            if worker_id not in data:
                return
            data[worker_id].update(fields)
            self._write(data)

    def remove(self, worker_id: str) -> None:
        with self._lock:
            data = self._read()
            if worker_id in data:
                del data[worker_id]
                self._write(data)

    def all(self) -> List[WorkerRecord]:
        with self._lock:
            return [WorkerRecord.from_dict(d) for d in self._read().values()]

