"""alertd 持久化/等待投递语义测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from alertd import AlertService


class FakeManager:
    def send(self, alert):
        return [
            {
                "name": "fake",
                "type": "fake",
                "ok": True,
                "attempts": 1,
                "error": "",
            }
        ]

    def channels(self):
        return ["fake"]

    def health(self):
        return []


class FlakyManager(FakeManager):
    def __init__(self):
        self.calls = 0

    def send(self, alert):
        self.calls += 1
        ok = self.calls >= 2
        return [
            {
                "name": "fake",
                "type": "fake",
                "ok": ok,
                "attempts": 1,
                "error": "" if ok else "transient",
            }
        ]


class AlertdServiceTests(unittest.TestCase):
    def test_wait_through_outbox_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "alertd": {
                    "db_file": str(Path(tmp) / "alerts.db"),
                    "log_file": str(Path(tmp) / "alerts.jsonl"),
                    "token": "",
                    "adapters": [],
                    "retry_backoff_seconds": 0,
                    "max_attempts": 2,
                    "workers": 1,
                }
            }
            service = AlertService(config)
            flaky = FlakyManager()
            service.adapter_manager = flaky
            service.start()
            try:
                item_id = service.enqueue("TRIP", "retry", "unit")
                result = service.wait_result(item_id, 5)
                self.assertEqual(result["status"], "delivered")
                self.assertGreaterEqual(flaky.calls, 2)
            finally:
                service.stop()

    def test_wait_for_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {
                "alertd": {
                    "db_file": str(Path(tmp) / "alerts.db"),
                    "log_file": str(Path(tmp) / "alerts.jsonl"),
                    "token": "",
                    "adapters": [],
                }
            }
            service = AlertService(config)
            service.adapter_manager = FakeManager()
            service.start()
            try:
                item_id = service.enqueue("TRIP", "test", "unit")
                result = service.wait_result(item_id, 5)
                self.assertEqual(result["status"], "delivered")
                self.assertTrue(result["ok"])
            finally:
                service.stop()


if __name__ == "__main__":
    unittest.main()
