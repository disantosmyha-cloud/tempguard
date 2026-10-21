"""手③：通知。

现在只做一件事：带时间戳打印到屏幕。
但结构上留好了手机推送的口子：以后在 _push_phone() 里实现即可，
main.py / fuse.py 一行都不用改。
"""

from __future__ import annotations

import datetime as _dt
import sys
from typing import Optional

INFO, WARN, TRIP = "INFO", "WARN", "TRIP"
_PREFIX = {INFO: "[信息]", WARN: "[警告]", TRIP: "[熔断]"}


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


def notify(level: str, message: str, config: Optional[dict] = None) -> bool:
    """发一条通知，返回是否至少有一个通道发出去了。

    config 传整份配置即可；notify 段缺失时默认打印。
    """
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = (config or {}).get("notify") or {}
    sent = False

    if cfg.get("print", True):
        prefix = _PREFIX.get(level, f"[{level}]")
        sent = _safe_print(f"{stamp} {prefix} {message}") or sent

    webhook = str((cfg.get("phone") or {}).get("webhook", "")).strip()
    if webhook:
        sent = _push_phone(webhook, level, message) or sent

    return sent


def _push_phone(webhook: str, level: str, message: str) -> bool:
    """TODO: 手机推送入口。

    可以接企业微信 / 钉钉 / Server酱 / Bark 等。
    实现时用 requests.post(webhook, json={...})，记得套 try/except，
    失败只返回 False，绝不能把异常抛回主循环。
    """
    return False
