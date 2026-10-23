"""S2：适配器熔断器。"""

from __future__ import annotations

import unittest

from adapters.base import Adapter, Alert
from adapters.manager import AdapterManager


class FailingAdapter(Adapter):
    type_name = "test"

    def __init__(self):
        super().__init__("failing", {"enabled": True})
        self.calls = 0

    def send(self, alert: Alert) -> bool:
        self.calls += 1
        return self.mark_error("expected failure")


class CircuitTests(unittest.TestCase):
    def test_open_circuit_skips_next_alert(self):
        adapter = FailingAdapter()
        manager = AdapterManager(
            [adapter],
            retry_attempts=1,
            circuit_failures=1,
            circuit_cooldown=60,
        )
        first = manager.send(Alert("INFO", "x", "now", "test"))
        self.assertFalse(first[0]["ok"])
        second = manager.send(Alert("INFO", "x", "now", "test"))
        self.assertFalse(second[0]["ok"])
        self.assertEqual(second[0]["attempts"], 0)
        self.assertEqual(adapter.calls, 1)


if __name__ == "__main__":
    unittest.main()
