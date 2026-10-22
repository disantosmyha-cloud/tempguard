"""QQ OneBot v11 HTTP 适配器。

不直接实现 QQ 协议，而是接 OneBot 实现（NapCat / Lagrange 等）的 HTTP API。
"""

from __future__ import annotations

from .base import Adapter, Alert
from .http import post_json


class QQOneBotAdapter(Adapter):
    type_name = "qq_onebot"

    def send(self, alert: Alert) -> bool:
        base_url = str(self.config.get("base_url") or "http://127.0.0.1:3000").rstrip("/")
        target_type = str(
            self.config.get("target_type")
            or self.config.get("message_type")
            or "group"
        ).strip().lower()
        target_id = str(
            self.config.get("target_id")
            or self.config.get("group_id")
            or self.config.get("user_id")
            or ""
        ).strip()
        if not target_id:
            return self.mark_error("缺少 target_id / group_id / user_id")

        if target_type in ("private", "friend", "user"):
            endpoint = "/send_private_msg"
            payload = {"user_id": target_id, "message": alert.text[:2000]}
        else:
            endpoint = "/send_group_msg"
            payload = {"group_id": target_id, "message": alert.text[:2000]}

        headers = {}
        token = str(self.config.get("access_token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        ok, data, error = post_json(
            base_url + endpoint,
            payload,
            timeout=self.timeout(),
            headers=headers,
        )
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        if isinstance(data, dict):
            if data.get("status") == "ok" or int(data.get("retcode", -1)) == 0:
                return self.mark_ok()
            return self.mark_error(str(data)[:300])
        return self.mark_ok()
