"""SMTP 邮件。"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .base import Adapter, Alert


class EmailAdapter(Adapter):
    type_name = "email"

    def send(self, alert: Alert) -> bool:
        host = str(self.config.get("smtp_host") or "").strip()
        from_addr = str(
            self.config.get("from_addr") or self.config.get("username") or ""
        ).strip()
        raw_to = self.config.get("to_addrs") or []
        if isinstance(raw_to, str):
            to_addrs = [raw_to.strip()] if raw_to.strip() else []
        else:
            to_addrs = [str(item).strip() for item in raw_to if str(item).strip()]
        if not host or not from_addr or not to_addrs:
            return self.mark_error("缺少 smtp_host / from_addr / to_addrs")

        try:
            port = int(self.config.get("smtp_port", 465) or 465)
        except (TypeError, ValueError):
            port = 465
        use_ssl = bool(self.config.get("use_ssl", True))
        starttls = bool(self.config.get("starttls", False))
        username = str(self.config.get("username") or "").strip()
        password = str(self.config.get("password") or "")
        timeout = self.timeout(10.0)

        try:
            msg = EmailMessage()
            msg["Subject"] = f"temguard{alert.prefix} 温度告警"
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_addrs)
            msg.set_content(alert.text)

            if use_ssl:
                server = smtplib.SMTP_SSL(host, port, timeout=timeout)
            else:
                server = smtplib.SMTP(host, port, timeout=timeout)
                if starttls:
                    server.starttls()
            try:
                if username:
                    server.login(username, password)
                server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
            return self.mark_ok()
        except Exception as exc:
            return self.mark_error(str(exc))
