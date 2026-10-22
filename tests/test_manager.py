"""适配器调度/重试测试。"""

from __future__ import annotations

import unittest

from adapters.base import Adapter, Alert
from adapters.manager import AdapterManager

ALERT = Alert("WARN", "test", "2026-10-22 21:00:00", "test")


class FlakyAdapter(Adapter):
    type_name = "flaky"

    def __init__(self, name: str):
        super().__init__(name, {"enabled": True})
        self.calls = 0

    def send(self, alert: Alert) -> bool:
        self.calls += 1
        if self.calls < 2:
            return self.mark_error("first failure")
        return self.mark_ok()


class DisabledAdapter(Adapter):
    type_name = "disabled"

    def __init__(self):
        super().__init__("disabled", {"enabled": False})

    def send(self, alert: Alert) -> bool:
        raise AssertionError("disabled adapter should not be called")


class ManagerTests(unittest.TestCase):
    def test_retry_per_adapter_and_skip_disabled(self):
        flaky = FlakyAdapter("flaky")
        manager = AdapterManager(
            [flaky, DisabledAdapter()],
            retry_attempts=2,
            retry_backoff=0,
        )
        results = manager.send(ALERT)
        self.assertEqual(flaky.calls, 2)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(results[0]["attempts"], 2)


if __name__ == "__main__":
    unittest.main()
