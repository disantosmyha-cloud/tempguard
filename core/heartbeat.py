"""可选的外部 heartbeat：让另一台机器/云监控发现 temguard 整机失联。

配置示例：

    monitor:
      heartbeat_url: "https://hc-ping.com/xxxxxxxx"
      heartbeat_interval_seconds: 60
      heartbeat_token: ""

这不是替代本地告警，而是补上“断电/断网/Windows 卡死时本机无法告警”的盲区。
"""

from __future__ import annotations

import json
import urllib.request


def send_heartbeat(
    url: str,
    token: str = "",
    payload: dict | None = None,
    timeout: float = 3.0,
) -> bool:
    url = str(url or "").strip()
    if not url:
        return False
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "temguard-heartbeat"}
    if token:
        headers["X-Heartbeat-Token"] = token
    try:
        request = urllib.request.Request(url, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False
