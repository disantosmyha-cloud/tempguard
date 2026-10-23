"""持久化告警发件箱。

alertd 不再把告警只放在内存队列里：每条告警先写入 SQLite，worker 再领取。
进程崩溃/重启后，pending/processing 的告警会重新入队，不会凭空消失。

优先级：TRIP=0，WARN=1，INFO=2，数字越小越先发。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_PRIORITY = {"TRIP": 0, "WARN": 1, "INFO": 2}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    level TEXT NOT NULL,
    priority INTEGER NOT NULL,
    message TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    results TEXT,
    delivered_at REAL
);
CREATE INDEX IF NOT EXISTS idx_outbox_pending
    ON outbox(status, priority, id);
"""


class OutboxFull(RuntimeError):
    pass


@dataclass
class OutboxItem:
    id: int
    created_at: float
    level: str
    priority: int
    message: str
    source: str
    attempts: int


class Outbox:
    def __init__(self, path: Path, max_pending: int = 1000):
        self.path = Path(path)
        self.max_pending = max(1, int(max_pending))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
            timeout=10,
        )
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._db.executescript(_SCHEMA)
            columns = {
                str(row[1])
                for row in self._db.execute("PRAGMA table_info(outbox)").fetchall()
            }
            if "next_attempt_at" not in columns:
                self._db.execute(
                    "ALTER TABLE outbox ADD COLUMN next_attempt_at REAL NOT NULL DEFAULT 0"
                )
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._db.close()
            except Exception:
                pass

    def reset_inflight(self) -> int:
        """进程崩溃时正在发送的条目重新排队。"""
        with self._lock:
            cur = self._db.execute(
                "UPDATE outbox SET status='pending', next_attempt_at=0 "
                "WHERE status='processing'"
            )
            self._db.commit()
            return cur.rowcount

    def pending_count(self) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM outbox WHERE status IN ('pending','processing')"
            ).fetchone()
            return int(row[0] if row else 0)

    def stats(self) -> dict:
        with self._lock:
            rows = self._db.execute(
                "SELECT status, COUNT(*) FROM outbox GROUP BY status"
            ).fetchall()
            return {str(status): int(count) for status, count in rows}

    def enqueue(self, level: str, message: str, source: str) -> int:
        with self._lock:
            pending = self.pending_count()
            if pending >= self.max_pending:
                raise OutboxFull(f"outbox 已满：{pending}/{self.max_pending}")
            priority = _PRIORITY.get(level, 1)
            cur = self._db.execute(
                "INSERT INTO outbox(created_at, level, priority, message, source, status) "
                "VALUES (?, ?, ?, ?, ?, 'pending')",
                (time.time(), level, priority, message, source),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def claim_next(self) -> Optional[OutboxItem]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute(
                    "SELECT id, created_at, level, priority, message, source, attempts "
                    "FROM outbox WHERE status='pending' AND next_attempt_at <= ? "
                    "ORDER BY priority ASC, id ASC LIMIT 1",
                    (time.time(),),
                ).fetchone()
                if row is None:
                    self._db.commit()
                    return None
                self._db.execute(
                    "UPDATE outbox SET status='processing', attempts=attempts+1 "
                    "WHERE id=?",
                    (row[0],),
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
            return OutboxItem(
                id=int(row[0]),
                created_at=float(row[1]),
                level=str(row[2]),
                priority=int(row[3]),
                message=str(row[4]),
                source=str(row[5]),
                attempts=int(row[6]) + 1,
            )

    def finish(
        self,
        item_id: int,
        ok: bool,
        results: list[dict],
        *,
        retry_after: Optional[float] = None,
        max_attempts: int = 3,
    ) -> str:
        """完成一条；失败且还有次数时回到 pending 并设置退避时间。"""
        if ok:
            status = "delivered"
        else:
            row = self._db.execute(
                "SELECT attempts FROM outbox WHERE id=?", (item_id,)
            ).fetchone()
            attempts = int(row[0] if row else 0)
            status = "pending" if retry_after is not None and attempts < max_attempts else "failed"
        with self._lock:
            if status == "pending":
                self._db.execute(
                    "UPDATE outbox SET status='pending', results=?, "
                    "next_attempt_at=? WHERE id=?",
                    (
                        json.dumps(results, ensure_ascii=False),
                        retry_after or time.time(),
                        item_id,
                    ),
                )
            else:
                self._db.execute(
                    "UPDATE outbox SET status=?, results=?, delivered_at=? "
                    "WHERE id=?",
                    (
                        status,
                        json.dumps(results, ensure_ascii=False),
                        time.time() if ok else None,
                        item_id,
                    ),
                )
            self._db.commit()
            return status

    def prune(self, retention_days: int = 30, max_history: int = 10000) -> int:
        """清理旧的已投递/失败记录，避免 SQLite 无限增长。"""
        cutoff = time.time() - max(1, int(retention_days)) * 86400
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM outbox WHERE status IN ('delivered','failed') "
                "AND (COALESCE(delivered_at, created_at) < ? "
                "OR id NOT IN (SELECT id FROM outbox "
                "WHERE status IN ('delivered','failed') "
                "ORDER BY id DESC LIMIT ?))",
                (cutoff, max(1, int(max_history))),
            )
            self._db.commit()
            return cur.rowcount

    def requeue_failed(self, item_id: int) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE outbox SET status='pending', attempts=0, results=NULL, "
                "next_attempt_at=0 WHERE id=? AND status IN ('failed','pending')",
                (int(item_id),),
            )
            self._db.commit()
            return cur.rowcount > 0

    def failures(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, created_at, level, source, message, attempts, results "
                "FROM outbox WHERE status='failed' ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [
            {
                "id": int(row[0]),
                "created_at": float(row[1]),
                "level": str(row[2]),
                "source": str(row[3]),
                "message": str(row[4])[:300],
                "attempts": int(row[5]),
                "results": json.loads(row[6]) if row[6] else [],
            }
            for row in rows
        ]
