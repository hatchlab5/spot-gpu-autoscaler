"""spot-gpu-autoscaler — autoscale spot GPUs with a hard cost cap and an out-of-band reaper."""

from .config import Config
from .models import Instance, WorkerRecord, InstanceStatus
from .autoscaler import AutoScaler
from .costguard import CostGuard, CostCapExceeded
from .reaper import Reaper
from .providers.base import Provider, ProviderError

__version__ = "0.1.0"

__all__ = [
    "Config",
    "Instance",
    "WorkerRecord",
    "InstanceStatus",
    "AutoScaler",
    "CostGuard",
    "CostCapExceeded",
    "Reaper",
    "Provider",
    "ProviderError",
    "__version__",
]

