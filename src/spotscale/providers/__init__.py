"""Provider adapters. `get_provider()` builds one by name from config/env."""

from __future__ import annotations

from .base import Provider, ProviderError
from .memory import MemoryProvider

__all__ = ["Provider", "ProviderError", "MemoryProvider", "get_provider"]


def get_provider(name: str = "vast", config=None, **kwargs) -> Provider:
    """Factory. `name` is 'vast' or 'memory' (or a custom-registered adapter).

    kwargs are passed to the adapter constructor.
    """
    name = (name or "vast").lower()
    if name == "memory":
        return MemoryProvider(**kwargs)
    if name == "vast":
        # Imported lazily so `memory` works with no networking imports at all.
        from .vast import VastProvider

        if config is not None:
            kwargs.setdefault("image", config.worker_image)
        return VastProvider(**kwargs)
    raise ProviderError(f"unknown provider: {name!r} (known: vast, memory)")

