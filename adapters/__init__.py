"""可插拔告警适配器。"""

from .base import Adapter, Alert
from .manager import AdapterManager
from .registry import build_adapters

__all__ = ["Adapter", "Alert", "AdapterManager", "build_adapters"]
