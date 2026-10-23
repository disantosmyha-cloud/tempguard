"""S2：alertd wait / 关键告警同步屏障的参数与返回语义。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from core import notify


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"status":"delivered","id":1}'


class NotifyTests(unittest.TestCase):
    def test_blocking_requires_delivered(self):
        config = {
            "notify": {
                "print": False,
                "mode": "alertd",
                "critical_wait_seconds": 1,
                "alertd": {
                    "enabled": True,
                    "url": "http://127.0.0.1:8765/alert",
                    "token": "",
                    "timeout_seconds": 1,
                },
            }
        }
        with patch("urllib.request.urlopen", return_value=FakeResponse()):
            self.assertTrue(
                notify.notify_blocking("TRIP", "x", config, timeout=1, idempotency_key="k")
            )

    def test_non_2xx_is_failure(self):
        with patch("urllib.request.urlopen", side_effect=OSError("down")):
            self.assertFalse(
                notify._push_alertd(
                    "http://127.0.0.1:1/alert", "", "INFO", "x", "now", 1
                )
            )


if __name__ == "__main__":
    unittest.main()
