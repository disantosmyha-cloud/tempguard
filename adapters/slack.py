"""Slack Incoming Webhook。"""

from __future__ import annotations

from .base import Adapter, Alert
from .http import post_json


class SlackAdapter(Adapter):
    type_name = "slack"

    def send(self, alert: Alert) -> bool:
        webhook = str(self.config.get("webhook") or "").strip()
        if not webhook:
            return self.mark_error("缺少 webhook")
        payload = {"text": alert.text[:3000]}
        channel = str(self.config.get("channel") or "").strip()
        if channel:
            payload["channel"] = channel
        ok, data, error = post_json(webhook, payload, timeout=self.timeout())
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        return self.mark_ok()
