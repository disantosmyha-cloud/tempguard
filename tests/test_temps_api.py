"""只读温度 API 的解析测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import alertd


class TempsApiTests(unittest.TestCase):
    def test_read_temps_tail_and_last(self):
        old = alertd.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            (root / "logs" / "temps.csv").write_text(
                "time,cpu,gpu,hottest,state,reason\n"
                "2026-01-01 00:00:00,60.0,50.0,60.0,safe,\n"
                "2026-01-01 00:00:05,61.0,51.0,61.0,warning,hot\n",
                encoding="utf-8",
            )
            alertd.ROOT = root
            try:
                rows = alertd._read_temps(10)
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[-1]["cpu"], 61.0)
                self.assertEqual(rows[-1]["state"], "warning")
            finally:
                alertd.ROOT = old


if __name__ == "__main__":
    unittest.main()
