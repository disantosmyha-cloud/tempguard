"""S1：跨进程熔断计时、动作日志、传感器新鲜度。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import main
from core.action_journal import ActionJournal
from core.fuse import Decision, Fuse, SHUTDOWN, TERMINATE
from core import sensors


class SafetyStateTests(unittest.TestCase):
    def test_fuse_restores_terminate_timer(self):
        thresholds = {
            "warning_c": 90,
            "terminate_c": 93,
            "shutdown_c": 100,
            "reset_c": 88,
            "terminate_seconds": 10,
            "shutdown_samples": 3,
        }
        fuse = Fuse(thresholds, cold_boot=False)
        self.assertEqual(fuse.feed({"cpu": 94}, now=0).state, "warning")
        self.assertEqual(fuse.feed({"cpu": 94}, now=9).state, "warning")
        state = fuse.export_state(now=9)
        self.assertGreaterEqual(state["terminate_held"], 9)

        restarted = Fuse(thresholds, cold_boot=False)
        restarted.restore_state(state, now=100)
        self.assertEqual(restarted.feed({"cpu": 94}, now=101).state, TERMINATE)

    def test_action_journal_retries_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = ActionJournal(Path(tmp) / "action.json")
            self.assertTrue(journal.should_attempt("shutdown", retry_seconds=0))
            journal.begin("shutdown", "test")
            journal.finish("shutdown", "failed", "boom")
            self.assertFalse(journal.should_attempt("shutdown", retry_seconds=60))
            journal.data["last_attempt_at"] = 0
            self.assertTrue(journal.should_attempt("shutdown", retry_seconds=60))

    def test_action_retry_after_failed_shutdown(self):
        calls = {"count": 0}

        def fake_shutdown(decision, config):
            calls["count"] += 1
            return calls["count"] >= 2

        original = main._handle_shutdown
        main._handle_shutdown = fake_shutdown
        try:
            with tempfile.TemporaryDirectory() as tmp:
                journal = ActionJournal(Path(tmp) / "action.json")
                decision = Decision(SHUTDOWN, None, None, ["test"])
                main._handle_state(decision, SHUTDOWN, {}, journal, retry_seconds=0)
                self.assertEqual(journal.status("shutdown"), "failed")
                main._handle_state(decision, SHUTDOWN, {}, journal, retry_seconds=0)
                self.assertEqual(journal.status("shutdown"), "scheduled")
                self.assertEqual(calls["count"], 2)
        finally:
            main._handle_shutdown = original

    def test_sensor_health_marks_missing_stale(self):
        sensors.reset_health()
        try:
            old_cpu = sensors.read_cpu_temperature
            old_gpu = sensors.read_gpu_temperature
            sensors.read_cpu_temperature = lambda: 50.0
            sensors.read_gpu_temperature = lambda: None
            sensors.read_temperatures()
            health = sensors.sensor_health(("cpu", "gpu"), stale_seconds=60)
            self.assertFalse(health["cpu"]["stale"])
            self.assertTrue(health["gpu"]["stale"])
        finally:
            sensors.read_cpu_temperature = old_cpu
            sensors.read_gpu_temperature = old_gpu
            sensors.reset_health()


if __name__ == "__main__":
    unittest.main()
