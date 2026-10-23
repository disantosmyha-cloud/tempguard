"""S3：关键动作处理器的安全/演习语义。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import main
from core.fuse import Decision, SHUTDOWN, TERMINATE, WARNING


class MainHandlerTests(unittest.TestCase):
    def test_dry_run_shutdown_returns_handled(self):
        decision = Decision(SHUTDOWN, 99.0, "cpu", ["test"])
        config = {"actions": {"dry_run": True, "shutdown_delay_seconds": 1}}
        with patch.object(main.notify_mod, "notify_blocking", return_value=True), patch.object(
            main.notify_mod, "notify"
        ):
            self.assertTrue(main._handle_shutdown(decision, config))

    def test_dry_run_terminate_returns_handled(self):
        decision = Decision(TERMINATE, 99.0, "cpu", ["test"])
        config = {
            "actions": {
                "dry_run": True,
                "terminate_processes": ["definitely-not-running.exe"],
            }
        }
        with patch.object(main.notify_mod, "notify_blocking", return_value=True), patch.object(
            main.notify_mod, "notify"
        ):
            self.assertTrue(main._handle_terminate(decision, config))

    def test_warning_transition_notifies_once(self):
        decision = Decision(WARNING, 91.0, "cpu", ["hot"])
        with patch.object(main.notify_mod, "notify") as notify:
            main._handle_state(decision, None, {})
            main._handle_state(decision, WARNING, {})
            self.assertEqual(notify.call_count, 1)


if __name__ == "__main__":
    unittest.main()
