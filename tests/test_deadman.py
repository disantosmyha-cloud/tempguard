"""死手开关接口/模拟实现测试。"""

from __future__ import annotations

import unittest

from core.deadman import MockDeadManSwitch, NullDeadManSwitch


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class DeadManTests(unittest.TestCase):
    def test_null_never_triggers(self):
        switch = NullDeadManSwitch()
        self.assertIsNone(switch.poll())
        self.assertFalse(switch.health()["enabled"])

    def test_manual_trigger_is_one_shot(self):
        switch = MockDeadManSwitch()
        switch.trigger("test")
        event = switch.poll()
        self.assertIsNotNone(event)
        self.assertEqual(event.source, "mock")
        self.assertIsNone(switch.poll())

    def test_timeout_requires_confirmation(self):
        clock = FakeClock()
        switch = MockDeadManSwitch(timeout_seconds=10, clock=clock)
        clock.now = 11
        event = switch.poll()
        self.assertIsNotNone(event)
        self.assertIn("no confirmation", event.reason)
        switch.confirm()
        clock.now = 30
        self.assertIsNotNone(switch.poll())


if __name__ == "__main__":
    unittest.main()
