"""可选的 AstrBot Open API 适配器。

保留它是为了个人微信/QQ 等非官方协议由 AstrBot 维护；官方平台可以直接
用本目录里的独立适配器，不需要 AstrBot。
"""

from __future__ import annotations

from .base import Adapter, Alert
from .http import post_json


class AstrBotAdapter(Adapter):
    type_name = "astrbot"

    def send(self, alert: Alert) -> bool:
        base_url = str(
            self.config.get("base_url") or "http://127.0.0.1:6185"
        ).rstrip("/")
        api_key = str(self.config.get("api_key") or "").strip()
        raw_umos = self.config.get("umos") or []
        if isinstance(raw_umos, str):
            umos = [raw_umos.strip()] if raw_umos.strip() else []
        else:
            umos = [str(item).strip() for item in raw_umos if str(item).strip()]
        if not api_key or not umos:
            return self.mark_error("缺少 api_key 或 umos")

        endpoint = base_url + "/api/v1/im/messages"
        sent_any = False
        last_error = ""
        for umo in umos:
            ok, data, error = post_json(
                endpoint,
                {"umo": umo, "message": alert.text[:2000]},
                timeout=self.timeout(),
                headers={"Authorization": f"ApiKey {api_key}"},
            )
            if ok and isinstance(data, dict) and data.get("status") == "ok":
                sent_any = True
            else:
                last_error = error or str(data)[:200]
        if sent_any:
            return self.mark_ok()
        return self.mark_error(last_error or "AstrBot 未确认")
