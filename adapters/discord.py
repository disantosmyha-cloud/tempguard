"""Discord Webhook。"""

from __future__ import annotations

from .base import Adapter, Alert
from .http import post_json


class DiscordAdapter(Adapter):
    type_name = "discord"

    def send(self, alert: Alert) -> bool:
        webhook = str(self.config.get("webhook") or "").strip()
        if not webhook:
            return self.mark_error("缺少 webhook")
        payload = {"content": alert.text[:1900]}
        username = str(self.config.get("username") or "").strip()
        if username:
            payload["username"] = username[:80]
        ok, data, error = post_json(webhook, payload, timeout=self.timeout())
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        return self.mark_ok()
