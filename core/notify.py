"""手③：通知。

当前支持两个通道：
- 带时间戳打印到屏幕（默认）；
- 企业微信群机器人 Webhook（配置 notify.wechat.webhook 后启用）。

企业微信机器人是官方 webhook，不需要额外 Python 包；网络请求放在后台线程里，
即使微信接口超时也不会拖住温度采样和熔断动作。

以后要加钉钉 / Server酱 / Bark，只需要在 _push_wechat 旁边加一个发送函数。
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import threading
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

INFO, WARN, TRIP = "INFO", "WARN", "TRIP"
_PREFIX = {INFO: "[信息]", WARN: "[警告]", TRIP: "[熔断]"}

_WECHAT_MAX_BYTES = 2000
_DEFAULT_TIMEOUT = 5.0


def _safe_print(text: str) -> bool:
    """控制台编码不支持某个字符时，替换掉而不是崩掉守护进程。"""
    try:
        print(text, flush=True)
        return True
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            print(
                text.encode(encoding, "replace").decode(encoding, "replace"),
                flush=True,
            )
            return True
        except Exception:
            return False
    except Exception:
        return False


def _as_list(value) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _wechat_config(cfg: dict) -> Tuple[str, List[str], List[str], float]:
    """读取微信配置；兼容旧版 notify.phone.webhook。"""
    section = cfg.get("wechat") or {}
    webhook = str(
        section.get("webhook")
        or (cfg.get("phone") or {}).get("webhook")
        or ""
    ).strip()
    mentions = _as_list(section.get("mentioned_list"))
    mobiles = _as_list(section.get("mentioned_mobile_list"))
    try:
        timeout = float(section.get("timeout_seconds", _DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT
    timeout = max(1.0, min(15.0, timeout))
    return webhook, mentions, mobiles, timeout


def _build_wechat_payload(
    level: str,
    message: str,
    stamp: str,
    mentions: List[str],
    mobiles: List[str],
) -> dict:
    prefix = _PREFIX.get(level, f"[{level}]")
    content = f"{stamp} {prefix} {message}"[:_WECHAT_MAX_BYTES]
    text = {"content": content}
    if mentions:
        text["mentioned_list"] = mentions
    if mobiles:
        text["mentioned_mobile_list"] = mobiles
    return {"msgtype": "text", "text": text}


def _valid_webhook(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    # 只额外允许本机 http，方便用 mock server 做测试。
    return parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")


def _push_wechat(webhook: str, payload: dict, timeout: float = _DEFAULT_TIMEOUT) -> bool:
    """同步发送一条企业微信机器人消息。失败返回 False，不抛异常。"""
    if not webhook or not _valid_webhook(webhook):
        return False
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            webhook,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
        result = json.loads(raw)
        return int(result.get("errcode", -1)) == 0
    except Exception:
        # 网络异常、超时、key 错误、返回体异常：一律按发送失败处理。
        return False


def _push_wechat_async(webhook: str, payload: dict, timeout: float) -> bool:
    """后台发送，避免微信接口卡住主循环。返回是否成功排入发送线程。"""
    try:
        thread = threading.Thread(
            target=_push_wechat,
            args=(webhook, payload, timeout),
            name="wechat-notify",
            daemon=True,
        )
        thread.start()
        return True
    except Exception:
        return False


def notify(level: str, message: str, config: Optional[dict] = None) -> bool:
    """发一条通知，返回是否至少有一个通道发出去了。

    config 传整份配置即可；notify 段缺失时默认只打印。
    微信通道是异步的：返回 True 表示已排入发送线程，不代表微信一定已收到。
    """
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = (config or {}).get("notify") or {}
    sent = False

    if cfg.get("print", True):
        prefix = _PREFIX.get(level, f"[{level}]")
        sent = _safe_print(f"{stamp} {prefix} {message}") or sent

    webhook, mentions, mobiles, timeout = _wechat_config(cfg)
    if webhook:
        payload = _build_wechat_payload(level, message, stamp, mentions, mobiles)
        sent = _push_wechat_async(webhook, payload, timeout) or sent

    return sent


def send_test(config: Optional[dict] = None) -> bool:
    """同步发送一条测试消息；用于 python main.py --test-wechat。"""
    cfg = (config or {}).get("notify") or {}
    webhook, mentions, mobiles, timeout = _wechat_config(cfg)
    if not webhook:
        return False
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = _build_wechat_payload(
        INFO, "企业微信机器人测试：temguard 告警通道正常", stamp, mentions, mobiles
    )
    return _push_wechat(webhook, payload, timeout)
