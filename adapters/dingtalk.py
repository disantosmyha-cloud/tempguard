"""钉钉群自定义机器人 Webhook（支持加签）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse

from .base import Adapter, Alert
from .http import post_json


class DingTalkAdapter(Adapter):
    type_name = "dingtalk"

    def send(self, alert: Alert) -> bool:
        webhook = str(self.config.get("webhook") or "").strip()
        if not webhook:
            return self.mark_error("缺少 webhook")
        secret = str(self.config.get("secret") or "").strip()
        if secret:
            timestamp = str(round(time.time() * 1000))
            string_to_sign = f"{timestamp}\n{secret}"
            digest = hmac.new(
                secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = urllib.parse.quote_plus(base64.b64encode(digest).decode("ascii"))
            joiner = "&" if "?" in webhook else "?"
            webhook = f"{webhook}{joiner}timestamp={timestamp}&sign={sign}"

        ok, data, error = post_json(
            webhook,
            {"msgtype": "text", "text": {"content": alert.text[:2000]}},
            timeout=self.timeout(),
        )
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        if isinstance(data, dict) and int(data.get("errcode", -1)) == 0:
            return self.mark_ok()
        return self.mark_error(str(data)[:300])
