"""适配器调度：逐个发送、逐适配器重试、汇总结果。"""

from __future__ import annotations

import time
from typing import Any

from .base import Adapter, Alert


class AdapterManager:
    def __init__(
        self,
        adapters: list[Adapter],
        *,
        retry_attempts: int = 3,
        retry_backoff: float = 2.0,
    ):
        self.adapters = adapters
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff = max(0.0, float(retry_backoff))

    def enabled_adapters(self) -> list[Adapter]:
        return [adapter for adapter in self.adapters if adapter.enabled]

    def channels(self) -> list[str]:
        return [adapter.name for adapter in self.enabled_adapters()]

    def health(self) -> list[dict[str, Any]]:
        return [adapter.health() for adapter in self.adapters]

    def send(self, alert: Alert) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for adapter in self.enabled_adapters():
            ok = False
            attempts = 0
            for attempts in range(1, self.retry_attempts + 1):
                try:
                    ok = adapter.send(alert)
                except Exception as exc:
                    adapter.mark_error(str(exc))
                    ok = False
                if ok:
                    break
                if attempts < self.retry_attempts:
                    time.sleep(self.retry_backoff * attempts)
            results.append(
                {
                    "name": adapter.name,
                    "type": adapter.type_name,
                    "ok": ok,
                    "attempts": attempts,
                    "error": adapter.last_error,
                }
            )
        return results
