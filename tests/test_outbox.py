"""持久化 outbox 测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.outbox import Outbox


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.outbox = Outbox(Path(self.tmp.name) / "alerts.db")

    def tearDown(self):
        self.outbox.close()
        self.tmp.cleanup()

    def test_priority_and_finish(self):
        info = self.outbox.enqueue("INFO", "info", "test")
        trip = self.outbox.enqueue("TRIP", "trip", "test")
        warn = self.outbox.enqueue("WARN", "warn", "test")
        first = self.outbox.claim_next()
        self.assertEqual(first.id, trip)
        self.outbox.finish(first.id, True, [{"ok": True}])
        second = self.outbox.claim_next()
        self.assertEqual(second.id, warn)
        self.outbox.finish(second.id, False, [{"ok": False}])
        third = self.outbox.claim_next()
        self.assertEqual(third.id, info)
        self.assertEqual(self.outbox.stats().get("delivered"), 1)
        self.assertEqual(self.outbox.stats().get("failed"), 1)
        self.assertEqual(len(self.outbox.failures()), 1)

    def test_failed_item_is_retried_until_max_attempts(self):
        item = self.outbox.enqueue("TRIP", "x", "test")
        first = self.outbox.claim_next()
        self.assertEqual(first.id, item)
        status = self.outbox.finish(
            first.id, False, [{"ok": False}], retry_after=0, max_attempts=2
        )
        self.assertEqual(status, "pending")
        second = self.outbox.claim_next()
        self.assertEqual(second.id, item)
        status = self.outbox.finish(
            second.id, False, [{"ok": False}], retry_after=0, max_attempts=2
        )
        self.assertEqual(status, "failed")

    def test_reset_inflight(self):
        item = self.outbox.enqueue("WARN", "x", "test")
        claimed = self.outbox.claim_next()
        self.assertEqual(claimed.id, item)
        self.assertEqual(self.outbox.reset_inflight(), 1)
        self.assertEqual(self.outbox.claim_next().id, item)


if __name__ == "__main__":
    unittest.main()
