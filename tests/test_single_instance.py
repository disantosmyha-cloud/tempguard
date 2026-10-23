"""S3：单实例锁。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.single_instance import AlreadyRunning, InstanceLock


class SingleInstanceTests(unittest.TestCase):
    def test_second_lock_fails_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = InstanceLock("test", Path(tmp)).acquire()
            try:
                with self.assertRaises(AlreadyRunning):
                    InstanceLock("test", Path(tmp)).acquire()
            finally:
                first.release()
            second = InstanceLock("test", Path(tmp)).acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
