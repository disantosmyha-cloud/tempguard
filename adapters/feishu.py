"""飞书 / Lark 群自定义机器人 Webhook。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from .base import Adapter, Alert
from .http import post_json


class FeishuAdapter(Adapter):
    type_name = "feishu"

    def send(self, alert: Alert) -> bool:
        webhook = str(self.config.get("webhook") or "").strip()
        if not webhook:
            return self.mark_error("缺少 webhook")
        payload: dict = {
            "msg_type": "text",
            "content": {"text": alert.text[:2000]},
        }
        secret = str(self.config.get("secret") or "").strip()
        if secret:
            timestamp = str(int(time.time()))
            string_to_sign = f"{timestamp}\n{secret}"
            digest = hmac.new(
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            payload["timestamp"] = timestamp
            payload["sign"] = base64.b64encode(digest).decode("ascii")

        ok, data, error = post_json(webhook, payload, timeout=self.timeout())
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        if isinstance(data, dict):
            code = data.get("code", data.get("StatusCode", 0))
            if int(code or 0) == 0:
                return self.mark_ok()
            return self.mark_error(str(data)[:300])
        return self.mark_ok()
