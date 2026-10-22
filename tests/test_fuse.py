"""熔断器安全语义测试。"""

from __future__ import annotations

import unittest

from core.fuse import Fuse, SHUTDOWN, WARNING


class FuseTests(unittest.TestCase):
    def test_cold_boot_grace_only_warns(self):
        fuse = Fuse(
            {"warning_c": 90, "terminate_c": 93, "shutdown_c": 95, "reset_c": 88,
             "terminate_seconds": 1, "shutdown_samples": 3},
            {"startup_grace_seconds": 180, "require_cool_baseline": True},
            cold_boot=True,
        )
        decisions = [fuse.feed({"cpu": 120}, now=float(i)) for i in range(5)]
        self.assertTrue(all(item.state != SHUTDOWN for item in decisions))
        self.assertEqual(decisions[-1].state, WARNING)

    def test_restart_in_same_boot_does_not_get_grace(self):
        fuse = Fuse(
            {"warning_c": 90, "terminate_c": 93, "shutdown_c": 95, "reset_c": 88,
             "terminate_seconds": 1, "shutdown_samples": 3},
            {"startup_grace_seconds": 180, "require_cool_baseline": True},
            cold_boot=False,
        )
        decisions = [fuse.feed({"cpu": 120}, now=float(i)) for i in range(3)]
        self.assertEqual(decisions[-1].state, SHUTDOWN)

    def test_no_sensor_is_warning_not_safe(self):
        fuse = Fuse(cold_boot=False)
        decision = fuse.feed({"cpu": None, "gpu": None})
        self.assertEqual(decision.state, WARNING)


if __name__ == "__main__":
    unittest.main()
