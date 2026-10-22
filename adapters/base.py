"""告警适配器基类和统一消息。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Alert:
    level: str
    message: str
    timestamp: str
    source: str = "temguard"

    @property
    def prefix(self) -> str:
        return {"INFO": "[信息]", "WARN": "[警告]", "TRIP": "[熔断]"}.get(
            self.level, f"[{self.level}]"
        )

    @property
    def text(self) -> str:
        return f"{self.timestamp} {self.prefix} {self.message}"

    def plain(self) -> str:
        return f"{self.prefix} {self.message}"


class Adapter:
    """一个消息出口。send() 返回 True 表示平台确认接收。"""

    type_name = "base"

    def __init__(self, name: str, config: Optional[dict] = None):
        self.name = str(name or self.type_name)
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))
        self.last_error = ""

    def send(self, alert: Alert) -> bool:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type_name,
            "enabled": self.enabled,
            "last_error": self.last_error,
        }

    def timeout(self, default: float = 5.0) -> float:
        try:
            value = float(self.config.get("timeout_seconds", default))
        except (TypeError, ValueError):
            value = default
        return max(1.0, min(60.0, value))

    def mark_error(self, message: str) -> bool:
        self.last_error = str(message)[:300]
        return False

    def mark_ok(self) -> bool:
        self.last_error = ""
        return True
