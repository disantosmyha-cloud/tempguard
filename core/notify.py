"""手③：通知。

支持三个通道，全部可独立开关：
- 带时间戳打印到屏幕；
- AstrBot Open API：由 AstrBot 路由到微信 / QQ / 飞书 / 钉钉 / Telegram /
  Discord / Slack 等已经接好的平台；
- 企业微信群机器人 Webhook（不经过 AstrBot 的备用通道）；
- SMTP 邮件（AstrBot 不负责邮件，所以这里单独发）。

网络发送全部放在后台线程，微信 / AstrBot / 邮件接口超时不会卡住温度采样和熔断。
任何通道失败都只返回 False，不抛异常，也不会把 key / 密码打印出来。
"""

from __future__ import annotations

import datetime as _dt
import json
import smtplib
import sys
import threading
import urllib.parse
import urllib.request
from email.message import EmailMessage
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


def _as_float(value, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(1.0, min(30.0, number))


def _async_send(func, *args) -> bool:
    """后台执行发送函数；返回是否成功启动线程，不代表对方已收到。"""
    try:
        threading.Thread(
            target=func,
            args=args,
            name="temguard-notify",
            daemon=True,
        ).start()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 消息内容

def _message_text(level: str, message: str, stamp: str) -> str:
    prefix = _PREFIX.get(level, f"[{level}]")
    return f"{stamp} {prefix} {message}"


# ---------------------------------------------------------------- AstrBot

def _astrbot_config(cfg: dict) -> Tuple[bool, str, str, List[str], float]:
    section = cfg.get("astrbot") or {}
    base_url = str(section.get("base_url") or "http://127.0.0.1:6185").rstrip("/")
    api_key = str(section.get("api_key") or "").strip()
    umos = _as_list(section.get("umos"))
    enabled = bool(section.get("enabled", bool(api_key and umos)))
    timeout = _as_float(section.get("timeout_seconds"), _DEFAULT_TIMEOUT)
    return enabled and bool(api_key and umos), base_url, api_key, umos, timeout


def _astrbot_endpoint(base_url: str) -> str:
    if base_url.endswith("/api/v1"):
        return base_url + "/im/messages"
    return base_url + "/api/v1/im/messages"


def _push_astrbot(
    base_url: str,
    api_key: str,
    umos: List[str],
    text: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> bool:
    """通过 AstrBot Open API 发送到一组 UMO（会话）。"""
    endpoint = _astrbot_endpoint(base_url)
    sent_any = False
    for umo in umos:
        try:
            body = json.dumps(
                {"umo": umo, "message": text[:2000]},
                ensure_ascii=False,
            ).encode("utf-8")
            request = urllib.request.Request(
                endpoint,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"ApiKey {api_key}",
                },
            )
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", "replace")
            result = json.loads(raw)
            if result.get("status") == "ok":
                sent_any = True
        except Exception:
            # 某个 UMO 失败不影响其他目标；错误详情不打印，避免泄露 key。
            continue
    return sent_any


# ---------------------------------------------------------------- 企业微信

def _wechat_config(cfg: dict) -> Tuple[str, List[str], List[str], float]:
    section = cfg.get("wechat") or {}
    webhook = str(
        section.get("webhook")
        or (cfg.get("phone") or {}).get("webhook")
        or ""
    ).strip()
    mentions = _as_list(section.get("mentioned_list"))
    mobiles = _as_list(section.get("mentioned_mobile_list"))
    timeout = _as_float(section.get("timeout_seconds"), _DEFAULT_TIMEOUT)
    return webhook, mentions, mobiles, timeout


def _build_wechat_payload(
    level: str,
    message: str,
    stamp: str,
    mentions: List[str],
    mobiles: List[str],
) -> dict:
    text = {"content": _message_text(level, message, stamp)[:_WECHAT_MAX_BYTES]}
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
        return False


# ---------------------------------------------------------------- 邮件

def _email_config(cfg: dict) -> Tuple[bool, dict]:
    section = cfg.get("email") or {}
    to_addrs = _as_list(section.get("to_addrs"))
    host = str(section.get("smtp_host") or "").strip()
    from_addr = str(section.get("from_addr") or section.get("username") or "").strip()
    enabled = bool(section.get("enabled", bool(host and to_addrs)))
    data = {
        "host": host,
        "port": int(section.get("smtp_port", 465) or 465),
        "use_ssl": bool(section.get("use_ssl", True)),
        "starttls": bool(section.get("starttls", False)),
        "username": str(section.get("username") or "").strip(),
        "password": str(section.get("password") or ""),
        "from_addr": from_addr,
        "to_addrs": to_addrs,
        "timeout": _as_float(section.get("timeout_seconds"), 10.0),
    }
    return enabled and bool(host and from_addr and to_addrs), data


def _push_email(data: dict, level: str, message: str, stamp: str) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = f"[temguard][{_PREFIX.get(level, level)}] 温度告警"
        msg["From"] = data["from_addr"]
        msg["To"] = ", ".join(data["to_addrs"])
        msg.set_content(_message_text(level, message, stamp))

        if data["use_ssl"]:
            server = smtplib.SMTP_SSL(
                data["host"], data["port"], timeout=data["timeout"]
            )
        else:
            server = smtplib.SMTP(
                data["host"], data["port"], timeout=data["timeout"]
            )
            if data["starttls"]:
                server.starttls()
        try:
            if data["username"]:
                server.login(data["username"], data["password"])
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True
    except Exception:
        # 网络、认证、邮件服务器错误都按发送失败处理。
        return False


# ---------------------------------------------------------------- 对外接口

def notify(level: str, message: str, config: Optional[dict] = None) -> bool:
    """发一条通知，返回是否至少有一个通道排入发送。

    所有网络通道都是后台发送：返回 True 只代表已交给发送线程，不代表对方已收到。
    """
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = (config or {}).get("notify") or {}
    text = _message_text(level, message, stamp)
    sent = False

    if cfg.get("print", True):
        sent = _safe_print(text) or sent

    # AstrBot：一次发到多个 UMO，由 AstrBot 路由到微信/QQ/飞书/钉钉等。
    enabled, base_url, api_key, umos, timeout = _astrbot_config(cfg)
    if enabled:
        sent = _async_send(_push_astrbot, base_url, api_key, umos, text, timeout) or sent

    # 企业微信群机器人：不经过 AstrBot 的备用直连通道。
    webhook, mentions, mobiles, wx_timeout = _wechat_config(cfg)
    if webhook:
        payload = _build_wechat_payload(level, message, stamp, mentions, mobiles)
        sent = _async_send(_push_wechat, webhook, payload, wx_timeout) or sent

    # 邮件：AstrBot 不覆盖邮件，单独走 SMTP。
    email_enabled, email_data = _email_config(cfg)
    if email_enabled:
        sent = _async_send(_push_email, email_data, level, message, stamp) or sent

    return sent


def send_test(config: Optional[dict] = None) -> bool:
    """同步发送一条测试消息到所有已配置通道。"""
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg = (config or {}).get("notify") or {}
    message = "temguard 告警通道测试：如果你收到这条消息，说明配置已经生效。"
    text = _message_text(INFO, message, stamp)
    sent = False

    enabled, base_url, api_key, umos, timeout = _astrbot_config(cfg)
    if enabled:
        sent = _push_astrbot(base_url, api_key, umos, text, timeout) or sent

    webhook, mentions, mobiles, wx_timeout = _wechat_config(cfg)
    if webhook:
        payload = _build_wechat_payload(INFO, message, stamp, mentions, mobiles)
        sent = _push_wechat(webhook, payload, wx_timeout) or sent

    email_enabled, email_data = _email_config(cfg)
    if email_enabled:
        sent = _push_email(email_data, INFO, message, stamp) or sent

    return sent
