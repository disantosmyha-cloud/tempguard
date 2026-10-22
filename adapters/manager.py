"""适配器调度：并行 fanout、逐适配器重试、汇总结果。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .base import Adapter, Alert


class AdapterManager:
    def __init__(
        self,
        adapters: list[Adapter],
        *,
        retry_attempts: int = 3,
        retry_backoff: float = 2.0,
        max_workers: int = 8,
    ):
        self.adapters = adapters
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.max_workers = max(1, int(max_workers))

    def enabled_adapters(self) -> list[Adapter]:
        return [adapter for adapter in self.adapters if adapter.enabled]

    def channels(self) -> list[str]:
        return [adapter.name for adapter in self.enabled_adapters()]

    def health(self) -> list[dict[str, Any]]:
        return [adapter.health() for adapter in self.adapters]

    def _send_one(self, adapter: Adapter, alert: Alert) -> dict[str, Any]:
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
        return {
            "name": adapter.name,
            "type": adapter.type_name,
            "ok": ok,
            "attempts": attempts,
            "error": adapter.last_error,
        }

    def send(self, alert: Alert) -> list[dict[str, Any]]:
        adapters = self.enabled_adapters()
        if not adapters:
            return []
        workers = min(self.max_workers, len(adapters))
        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="alert-adapter",
        ) as pool:
            # map 保持适配器顺序，便于日志稳定对比。
            return list(pool.map(lambda adapter: self._send_one(adapter, alert), adapters))
