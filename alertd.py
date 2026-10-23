"""独立告警服务 alertd。

可靠性约束：

1. 每条告警先写入 SQLite outbox，再发送；进程崩溃/重启不丢 pending。
2. TRIP 优先于 WARN，WARN 优先于 INFO。
3. 适配器并行 fanout，单个通道超时不会阻塞其他通道。
4. 支持 `wait=true`：temguard 在关机/终止进程前可以同步等待投递结果。

运行：
    python alertd.py

健康检查：
    http://127.0.0.1:8765/health
"""

from __future__ import annotations

import argparse
import datetime as dt
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import yaml

from adapters import AdapterManager, Alert, build_adapters
from core.config import validate_config
from core.outbox import Outbox, OutboxFull
from core.secrets import resolve_config
from core.single_instance import AlreadyRunning, InstanceLock

ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 64 * 1024
MAX_LOG_BYTES = 5 * 1024 * 1024
DEFAULT_WAIT_SECONDS = 10.0


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return validate_config(resolve_config(yaml.safe_load(fh) or {}))


def default_config_path() -> Path:
    local = ROOT / "config.local.yaml"
    return local if local.exists() else ROOT / "config.yaml"


class AlertService:
    def __init__(self, config: dict):
        self.config = config
        cfg = config.get("alertd") or {}
        self.host = str(cfg.get("host") or DEFAULT_HOST)
        self.port = int(cfg.get("port") or DEFAULT_PORT)
        self.token = str(cfg.get("token") or "").strip()
        self.retry_attempts = max(1, int(cfg.get("retry_attempts", 3)))
        self.retry_backoff = max(0.0, float(cfg.get("retry_backoff_seconds", 2)))
        self.max_attempts = max(1, int(cfg.get("max_attempts", 3)))
        self.required_adapters = [
            str(name).strip()
            for name in (cfg.get("required_adapters") or [])
            if str(name).strip()
        ]
        self.default_wait = max(
            1.0,
            min(30.0, float(cfg.get("wait_default_seconds", DEFAULT_WAIT_SECONDS))),
        )
        self.adapter_manager = AdapterManager(
            build_adapters(config),
            retry_attempts=self.retry_attempts,
            retry_backoff=self.retry_backoff,
        )

        db_file = Path(cfg.get("db_file") or "logs/alerts.db")
        if not db_file.is_absolute():
            db_file = ROOT / db_file
        self.outbox = Outbox(
            db_file,
            max_pending=int(cfg.get("max_pending", 1000)),
        )
        self.outbox.prune(
            retention_days=int(cfg.get("retention_days", 30)),
            max_history=int(cfg.get("max_history", 10000)),
        )
        self.log_path = Path(cfg.get("log_file") or "logs/alerts.jsonl")
        if not self.log_path.is_absolute():
            self.log_path = ROOT / self.log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_lock = threading.Lock()

        self._waiters_lock = threading.Lock()
        self._waiters: dict[int, threading.Event] = {}
        self._completed: dict[int, dict] = {}
        self._stop = threading.Event()
        worker_count = max(1, min(8, int(cfg.get("workers", 2))))
        self._workers = [
            threading.Thread(
                target=self._run_worker,
                name=f"alertd-worker-{index + 1}",
                daemon=True,
            )
            for index in range(worker_count)
        ]

    def start(self) -> None:
        recovered = self.outbox.reset_inflight()
        if recovered:
            self._append_log(
                {
                    "time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "event": "recovered_inflight",
                    "count": recovered,
                }
            )
        for worker in self._workers:
            worker.start()

    def stop(self) -> None:
        self._stop.set()
        for worker in self._workers:
            try:
                worker.join(timeout=5)
            except Exception:
                pass
        self.outbox.close()

    def enqueue(self, level: str, message: str, source: str) -> int:
        return self.outbox.enqueue(level, message[:2000], source)

    def wait_result(self, item_id: int, timeout: float) -> dict:
        timeout = max(1.0, min(30.0, float(timeout)))
        event = threading.Event()
        with self._waiters_lock:
            done = self._completed.get(item_id)
            if done is not None:
                return done
            self._waiters[item_id] = event
        try:
            if event.wait(timeout):
                with self._waiters_lock:
                    return self._completed.get(
                        item_id,
                        {"id": item_id, "status": "accepted"},
                    )
            return {"id": item_id, "status": "accepted"}
        finally:
            with self._waiters_lock:
                self._waiters.pop(item_id, None)

    def channels(self) -> list:
        return self.adapter_manager.channels()

    def health(self) -> dict:
        return {
            "status": "ok",
            "pending": self.outbox.pending_count(),
            "outbox": self.outbox.stats(),
            "channels": self.channels(),
            "adapters": self.adapter_manager.health(),
            "failures": self.outbox.failures(5),
        }

    def _run_worker(self) -> None:
        while not self._stop.is_set():
            item = self.outbox.claim_next()
            if item is None:
                self._stop.wait(0.25)
                continue

            alert = Alert(
                level=item.level,
                message=item.message,
                timestamp=dt.datetime.fromtimestamp(item.created_at).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                source=item.source,
            )
            try:
                results = self.adapter_manager.send(alert)
            except Exception as exc:
                results = [
                    {
                        "name": "manager",
                        "type": "manager",
                        "ok": False,
                        "attempts": 0,
                        "error": str(exc)[:300],
                    }
                ]
            any_ok = any(result.get("ok") for result in results)
            delivered = any_ok
            if item.level == "TRIP" and self.required_adapters:
                delivered = all(
                    any(
                        result.get("name") == required and result.get("ok")
                        for result in results
                    )
                    for required in self.required_adapters
                )
            status = self.outbox.finish(
                item.id,
                delivered,
                results,
                retry_after=time.time()
                + self.retry_backoff * max(1, item.attempts),
                max_attempts=self.max_attempts,
            )
            payload = {
                "id": item.id,
                "time": alert.timestamp,
                "level": item.level,
                "source": item.source,
                "message": item.message,
                "ok": delivered,
                "status": status,
                "attempts": max(
                    (int(result.get("attempts") or 0) for result in results),
                    default=0,
                ),
                "results": results,
            }
            self._append_log(payload)
            self._complete(item.id, payload)

    def _complete(self, item_id: int, payload: dict) -> None:
        with self._waiters_lock:
            self._completed[item_id] = payload
            event = self._waiters.get(item_id)
            if event is not None:
                event.set()
            # 避免 completed 无限增长；保留最近 2000 条。
            if len(self._completed) > 2000:
                for key in sorted(self._completed)[:1000]:
                    self._completed.pop(key, None)

    def _append_log(self, record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._log_lock:
            try:
                if self.log_path.exists() and self.log_path.stat().st_size > MAX_LOG_BYTES:
                    backup = self.log_path.with_suffix(self.log_path.suffix + ".1")
                    try:
                        self.log_path.replace(backup)
                    except Exception:
                        pass
                with open(self.log_path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except Exception:
                pass


def _make_handler(service: AlertService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "temguard-alertd/2.0"

        def log_message(self, fmt, *args):
            return

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not service.token:
                return True
            supplied = self.headers.get("X-Alert-Token", "").strip()
            if not supplied:
                auth = self.headers.get("Authorization", "").strip()
                if auth.lower().startswith("bearer "):
                    supplied = auth[7:].strip()
            return hmac.compare_digest(supplied, service.token)

        def do_GET(self):
            if self.path != "/health":
                self._send(404, {"status": "error", "message": "not found"})
                return
            self._send(200, service.health())

        def do_POST(self):
            if self.path not in ("/alert", "/retry"):
                self._send(404, {"status": "error", "message": "not found"})
                return
            if not self._authorized():
                self._send(401, {"status": "error", "message": "unauthorized"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > MAX_BODY_BYTES:
                self._send(413, {"status": "error", "message": "bad body size"})
                return

            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                self._send(400, {"status": "error", "message": "invalid json"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"status": "error", "message": "invalid payload"})
                return

            if self.path == "/retry":
                try:
                    item_id = int(payload.get("id"))
                except (TypeError, ValueError):
                    self._send(400, {"status": "error", "message": "invalid id"})
                    return
                if not service.outbox.requeue_failed(item_id):
                    self._send(404, {"status": "error", "message": "failed item not found"})
                    return
                self._send(200, {"status": "requeued", "id": item_id})
                return

            level = str(payload.get("level") or "INFO").upper()
            message = str(payload.get("message") or "").strip()
            source = str(payload.get("source") or "temguard")[:100]
            if level not in ("INFO", "WARN", "TRIP"):
                self._send(400, {"status": "error", "message": "invalid level"})
                return
            if not message:
                self._send(400, {"status": "error", "message": "empty message"})
                return

            try:
                item_id = service.enqueue(level, message, source)
            except OutboxFull as exc:
                self._send(503, {"status": "error", "message": str(exc)})
                return
            except Exception as exc:
                self._send(500, {"status": "error", "message": str(exc)[:300]})
                return

            if payload.get("wait"):
                try:
                    wait_seconds = float(
                        payload.get("timeout_seconds", service.default_wait)
                    )
                except (TypeError, ValueError):
                    wait_seconds = service.default_wait
                self._send(200, service.wait_result(item_id, wait_seconds))
                return
            self._send(202, {"status": "accepted", "id": item_id})

    return Handler


def run(config_path: Path) -> int:
    config = load_config(config_path)
    try:
        lock = InstanceLock("alertd", ROOT / "logs").acquire()
    except AlreadyRunning as exc:
        print(f"alertd 未启动：{exc}")
        return 0
    service = None
    httpd = None
    try:
        service = AlertService(config)
        service.start()
        handler = _make_handler(service)
        try:
            httpd = ThreadingHTTPServer((service.host, service.port), handler)
        except OSError as exc:
            print(f"alertd 启动失败：{service.host}:{service.port} 无法监听：{exc}")
            return 1
        httpd.daemon_threads = True
        print(
            f"alertd 已启动：http://{service.host}:{service.port} "
            f"channels={','.join(service.channels()) or 'none'} "
            f"pending={service.outbox.pending_count()}",
            flush=True,
        )
        try:
            httpd.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        return 0
    finally:
        if service is not None:
            service.stop()
        if httpd is not None:
            httpd.server_close()
        lock.release()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="temguard 独立告警服务")
    parser.add_argument("--config", default=str(default_config_path()), help="配置文件路径")
    args = parser.parse_args(argv)
    return run(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
