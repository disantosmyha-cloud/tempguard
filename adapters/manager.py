"""适配器调度：并行 fanout、逐适配器重试、汇总结果。"""

from __future__ import annotations

import random
import threading
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
        circuit_failures: int = 3,
        circuit_cooldown: float = 60.0,
    ):
        self.adapters = adapters
        self.retry_attempts = max(1, int(retry_attempts))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.max_workers = max(1, int(max_workers))
        self.circuit_failures = max(1, int(circuit_failures))
        self.circuit_cooldown = max(1.0, float(circuit_cooldown))
        self._circuit_lock = threading.Lock()
        self._circuits: dict[str, dict] = {}

    def enabled_adapters(self) -> list[Adapter]:
        return [adapter for adapter in self.adapters if adapter.enabled]

    def channels(self) -> list[str]:
        return [adapter.name for adapter in self.enabled_adapters()]

    def health(self) -> list[dict[str, Any]]:
        result = []
        with self._circuit_lock:
            circuits = {key: dict(value) for key, value in self._circuits.items()}
        for adapter in self.adapters:
            item = adapter.health()
            item["circuit"] = circuits.get(adapter.name, {})
            result.append(item)
        return result

    def _circuit_state(self, name: str) -> dict:
        with self._circuit_lock:
            return dict(self._circuits.get(name, {}))

    def _mark_circuit(self, name: str, ok: bool) -> None:
        now = time.time()
        with self._circuit_lock:
            state = self._circuits.setdefault(
                name, {"failures": 0, "open_until": 0.0}
            )
            if ok:
                state["failures"] = 0
                state["open_until"] = 0.0
                return
            state["failures"] = int(state.get("failures", 0)) + 1
            if state["failures"] >= self.circuit_failures:
                state["open_until"] = now + self.circuit_cooldown

    def _send_one(self, adapter: Adapter, alert: Alert) -> dict[str, Any]:
        state = self._circuit_state(adapter.name)
        if float(state.get("open_until", 0)) > time.time():
            return {
                "name": adapter.name,
                "type": adapter.type_name,
                "ok": False,
                "attempts": 0,
                "error": "circuit open，等待冷却",
            }

        ok = False
        attempts = 0
        last_error = ""
        for attempts in range(1, self.retry_attempts + 1):
            try:
                ok = adapter.send(alert)
            except Exception as exc:
                adapter.mark_error(str(exc))
                ok = False
            if ok:
                break
            last_error = adapter.last_error or last_error
            if attempts < self.retry_attempts:
                jitter = random.uniform(0.75, 1.25)
                time.sleep(self.retry_backoff * attempts * jitter)
        self._mark_circuit(adapter.name, ok)
        return {
            "name": adapter.name,
            "type": adapter.type_name,
            "ok": ok,
            "attempts": attempts,
            "error": last_error,
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
