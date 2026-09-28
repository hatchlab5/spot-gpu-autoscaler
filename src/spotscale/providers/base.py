"""The provider interface. Three methods; nothing more is required."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import Instance


class ProviderError(RuntimeError):
    """Raised when a provider call fails (network, auth, no capacity, bad response)."""


class Provider(ABC):
    """A spot-GPU provider.

    Implementations must not put credentials on argv or in logs; read them from
    the environment or an injected value held in memory.
    """

    #: short stable identifier stored on each WorkerRecord
    name: str = "base"

    @abstractmethod
    def spin(self, gpu: str, max_price: float, label: str = "") -> Instance:
        """Create one instance of `gpu` at or below `max_price` $/hr.

        Returns the created Instance (with id and real price). Raises
        ProviderError if nothing could be created.
        """

    @abstractmethod
    def list(self) -> List[Instance]:
        """Return every instance the account currently has (any status)."""

    @abstractmethod
    def kill(self, instance_id: str) -> bool:
        """Destroy an instance. Return True if it is gone (or already gone)."""

