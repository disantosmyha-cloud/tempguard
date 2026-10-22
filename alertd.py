"""独立告警服务 alertd。

架构：

    temguard --HTTP--> alertd --+--> AstrBot Open API --> 微信/QQ/飞书/钉钉/Telegram...
                                +--> 企业微信群机器人直连
                                +--> SMTP 邮件
                                +--> logs/alerts.jsonl

AstrBot 只作为“协议适配层”，alertd 自己负责接收、排队、重试、记录和分发告警。
这样换掉 AstrBot 或增加官方 Webhook，都不用改 temguard 主循环。

运行：
    python alertd.py
    python alertd.py --config config.local.yaml

健康检查：
    http://127.0.0.1:8765/health
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

import yaml

from core import notify as notify_mod

ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 64 * 1024
MAX_LOG_BYTES = 5 * 1024 * 1024


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


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
        self.queue: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=200)
        self.log_path = Path(cfg.get("log_file") or "logs/alerts.jsonl")
        if not self.log_path.is_absolute():
            self.log_path = ROOT / self.log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._run_worker,
            name="alertd-worker",
            daemon=True,
        )

    def start(self) -> None:
        self._worker.start()

    def enqueue(self, level: str, message: str, source: str) -> None:
        self.queue.put_nowait((level, message, source))

    def channels(self) -> list:
        cfg = self.config.get("notify") or {}
        names = []
        astrbot = cfg.get("astrbot") or {}
        if astrbot.get("enabled") and astrbot.get("api_key") and astrbot.get("umos"):
            names.append("astrbot")
        if ((cfg.get("wechat") or {}).get("webhook") or (cfg.get("phone") or {}).get("webhook")):
            names.append("wechat")
        if (cfg.get("email") or {}).get("enabled") and (cfg.get("email") or {}).get("to_addrs"):
            names.append("email")
        return names

    def _run_worker(self) -> None:
        while True:
            item = self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            level, message, source = item
            ok = False
            attempts = 0
            for attempts in range(1, self.retry_attempts + 1):
                try:
                    ok = notify_mod.send_direct(self.config, level, message, False)
                except Exception:
                    ok = False
                if ok:
                    break
                if attempts < self.retry_attempts:
                    time.sleep(self.retry_backoff * attempts)
            self._append_log(
                {
                    "time": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "level": level,
                    "source": source,
                    "message": message,
                    "ok": ok,
                    "attempts": attempts,
                }
            )
            self.queue.task_done()

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
        server_version = "temguard-alertd/1.0"

        def log_message(self, fmt, *args):
            return  # 不把访问日志打到找不到的控制台

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
            return supplied == service.token

        def do_GET(self):
            if self.path != "/health":
                self._send(404, {"status": "error", "message": "not found"})
                return
            self._send(
                200,
                {
                    "status": "ok",
                    "queue": service.queue.qsize(),
                    "channels": service.channels(),
                },
            )

        def do_POST(self):
            if self.path != "/alert":
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
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                self._send(400, {"status": "error", "message": "invalid json"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"status": "error", "message": "invalid payload"})
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
                service.enqueue(level, message[:2000], source)
            except queue.Full:
                self._send(503, {"status": "error", "message": "queue full"})
                return
            self._send(202, {"status": "accepted"})

    return Handler


def run(config_path: Path) -> int:
    config = load_config(config_path)
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
        f"channels={','.join(service.channels()) or 'none'}",
        flush=True,
    )
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            service.queue.put_nowait(None)
        except Exception:
            pass
        httpd.server_close()
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="temguard 独立告警服务")
    parser.add_argument("--config", default=str(default_config_path()), help="配置文件路径")
    args = parser.parse_args(argv)
    return run(Path(args.config))


if __name__ == "__main__":
    raise SystemExit(main())
