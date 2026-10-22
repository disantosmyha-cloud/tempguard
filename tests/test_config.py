"""配置校验测试。"""

from __future__ import annotations

import unittest

from core.config import ConfigError, validate_config


class ConfigTests(unittest.TestCase):
    def test_minimal_valid(self):
        cfg = validate_config({
            "sample": {"interval_seconds": 5},
            "thresholds": {"reset_c": 88, "warning_c": 90, "terminate_c": 93, "shutdown_c": 95},
            "notify": {"mode": "alertd"},
            "alertd": {"port": 8765, "adapters": [{"type": "wecom", "enabled": False}]},
        })
        self.assertEqual(cfg["notify"]["mode"], "alertd")

    def test_invalid_threshold_order(self):
        with self.assertRaises(ConfigError):
            validate_config({
                "thresholds": {"reset_c": 95, "warning_c": 90, "terminate_c": 93, "shutdown_c": 96},
            })

    def test_invalid_mode(self):
        with self.assertRaises(ConfigError):
            validate_config({"notify": {"mode": "telepathy"}})


if __name__ == "__main__":
    unittest.main()
