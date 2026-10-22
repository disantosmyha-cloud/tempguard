"""Telegram Bot API。"""

from __future__ import annotations

from .base import Adapter, Alert
from .http import post_json


class TelegramAdapter(Adapter):
    type_name = "telegram"

    def send(self, alert: Alert) -> bool:
        token = str(self.config.get("bot_token") or "").strip()
        chat_id = str(self.config.get("chat_id") or "").strip()
        if not token or not chat_id:
            return self.mark_error("缺少 bot_token 或 chat_id")
        api_base = str(
            self.config.get("api_base") or "https://api.telegram.org"
        ).rstrip("/")
        url = f"{api_base}/bot{token}/sendMessage"
        ok, data, error = post_json(
            url,
            {
                "chat_id": chat_id,
                "text": alert.text[:4000],
                "disable_web_page_preview": True,
            },
            timeout=self.timeout(),
        )
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        if isinstance(data, dict) and data.get("ok"):
            return self.mark_ok()
        return self.mark_error(str(data)[:300])
