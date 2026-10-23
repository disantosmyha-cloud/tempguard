"""关键动作日志：让 terminate/shutdown 失败后可重试，且可跨进程恢复。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional


class ActionJournal:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict = {}
        self.load()

    def load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = value if isinstance(value, dict) else {}
        except Exception:
            self.data = {}
        return self.data

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        except Exception:
            pass

    def status(self, action: str) -> str:
        if self.data.get("action") != action:
            return "none"
        return str(self.data.get("status") or "none")

    def should_attempt(self, action: str, retry_seconds: float = 60.0) -> bool:
        if self.data.get("action") != action:
            return True
        status = str(self.data.get("status") or "none")
        if status in ("scheduled", "done"):
            return False
        try:
            last = float(self.data.get("last_attempt_at") or 0)
        except (TypeError, ValueError):
            last = 0.0
        return time.time() - last >= max(0.0, retry_seconds)

    def begin(self, action: str, reason: str = "") -> None:
        previous_attempts = 0
        if self.data.get("action") == action:
            try:
                previous_attempts = int(self.data.get("attempts") or 0)
            except (TypeError, ValueError):
                previous_attempts = 0
        self.data = {
            "action": action,
            "status": "pending",
            "attempts": previous_attempts + 1,
            "last_attempt_at": time.time(),
            "reason": reason,
            "last_error": "",
        }
        self._save()

    def finish(self, action: str, status: str, error: str = "") -> None:
        if self.data.get("action") != action:
            self.begin(action)
        self.data["status"] = status
        self.data["last_error"] = error[:500]
        self.data["updated_at"] = time.time()
        self._save()

    def clear(self) -> None:
        self.data = {}
        self._save()

    def attempts(self) -> int:
        try:
            return int(self.data.get("attempts") or 0)
        except (TypeError, ValueError):
            return 0
