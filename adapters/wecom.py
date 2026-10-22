"""企业微信群机器人 Webhook。"""

from __future__ import annotations

from .base import Adapter, Alert
from .http import post_json


class WeComAdapter(Adapter):
    type_name = "wecom"

    def send(self, alert: Alert) -> bool:
        webhook = str(self.config.get("webhook") or "").strip()
        if not webhook:
            return self.mark_error("缺少 webhook")
        text: dict = {"content": alert.text[:2000]}
        mentions = self.config.get("mentioned_list") or []
        mobiles = self.config.get("mentioned_mobile_list") or []
        if mentions:
            text["mentioned_list"] = mentions
        if mobiles:
            text["mentioned_mobile_list"] = mobiles
        ok, data, error = post_json(
            webhook,
            {"msgtype": "text", "text": text},
            timeout=self.timeout(),
        )
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        if isinstance(data, dict) and int(data.get("errcode", -1)) == 0:
            return self.mark_ok()
        return self.mark_error(str(data)[:300])
