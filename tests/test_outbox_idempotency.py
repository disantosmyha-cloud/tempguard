"""S2：outbox 幂等键。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.outbox import Outbox


class OutboxIdempotencyTests(unittest.TestCase):
    def test_duplicate_key_returns_same_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = Outbox(Path(tmp) / "alerts.db")
            try:
                first = outbox.enqueue("TRIP", "x", "test", idempotency_key="k1")
                second = outbox.enqueue("TRIP", "x", "test", idempotency_key="k1")
                self.assertEqual(first, second)
            finally:
                outbox.close()


if __name__ == "__main__":
    unittest.main()
