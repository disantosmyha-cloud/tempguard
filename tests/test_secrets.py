"""S3：DPAPI 存取和占位符解析。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from core import secrets


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class SecretsTests(unittest.TestCase):
    def test_roundtrip_and_placeholder(self):
        import core.secrets as module

        old = module.VAULT
        with tempfile.TemporaryDirectory() as tmp:
            module.VAULT = Path(tmp) / "secrets.dat"
            try:
                secrets.set_secret("k", "v")
                self.assertEqual(secrets.get_secret("k"), "v")
                self.assertEqual(secrets.resolve_value("${secret:k}"), "v")
                self.assertEqual(secrets.resolve_config({"x": ["${secret:k}"]}), {"x": ["v"]})
            finally:
                module.VAULT = old


if __name__ == "__main__":
    unittest.main()
