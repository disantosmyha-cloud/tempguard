"""通用微信桥接 Webhook。

用于 Wechaty / WeChatFerry / 其他本地微信桥。它们通常已经负责登录微信，
我们只把告警 POST 给桥的发送接口。

请求：
    POST {url}
    {"level":"TRIP","message":"...","text":"...","timestamp":"..."}

桥返回 2xx 即视为成功；如果返回 JSON 且含 "ok": false，则视为失败。
"""

from __future__ import annotations

from .base import Adapter, Alert
from .http import post_json


class WeChatHookAdapter(Adapter):
    type_name = "wechat_hook"

    def send(self, alert: Alert) -> bool:
        url = str(self.config.get("url") or "").strip()
        if not url:
            return self.mark_error("缺少 url")
        headers = {}
        token = str(self.config.get("token") or "").strip()
        if token:
            headers["X-Alert-Token"] = token
            headers["Authorization"] = f"Bearer {token}"
        ok, data, error = post_json(
            url,
            {
                "level": alert.level,
                "message": alert.message,
                "text": alert.text,
                "timestamp": alert.timestamp,
                "source": alert.source,
            },
            timeout=self.timeout(),
            headers=headers,
        )
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        if isinstance(data, dict) and data.get("ok") is False:
            return self.mark_error(str(data)[:300])
        return self.mark_ok()
