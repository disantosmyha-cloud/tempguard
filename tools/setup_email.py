"""配置 QQ 邮箱 SMTP 的一步式脚本。

用法：
    python tools/setup_email.py

它会：
1. 用 getpass 读取 QQ 邮箱“SMTP 授权码”（不是登录密码）；
2. 加密写入 Windows DPAPI secrets.dat；
3. 用现有 email 适配器发一封测试邮件；
4. 只有发送成功，才把 alertd 的 email 适配器启用，
   并把 TRIP 的关键通道设置为 email。
"""

from __future__ import annotations

import getpass
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.base import Alert
from adapters.email import EmailAdapter
from core import secrets
import main as temguard_main


def main() -> int:
    code = getpass.getpass("QQ邮箱 SMTP 授权码（不是登录密码）: ").strip()
    if not code:
        print("授权码为空，未修改")
        return 1
    secrets.set_secret("email_password", code)
    config = temguard_main.load_config(ROOT / "config.local.yaml")
    email = next(
        (a for a in (config.get("alertd") or {}).get("adapters", []) if a.get("type") == "email"),
        None,
    )
    if not email:
        print("config.local.yaml 里没有 email 适配器")
        return 1
    email = dict(email)
    email["enabled"] = True
    adapter = EmailAdapter("email", email)
    ok = adapter.send(
        Alert(
            "INFO",
            "temguard 邮件通道测试：如果你收到这封邮件，说明 SMTP 配置已经生效。",
            "2026-01-01 00:00:00",
            "setup-email",
        )
    )
    if not ok:
        print(f"邮件发送失败：{adapter.last_error}")
        print("授权码已加密保存，但 email 适配器仍未启用。")
        return 1

    path = ROOT / "config.local.yaml"
    text = path.read_text(encoding="utf-8")
    # 只启用 email 这一个块的 enabled: false。
    text = re.sub(
        r"(?ms)(    - name: email\n(?:.*\n)*?      enabled: )false",
        r"\1true",
        text,
        count=1,
    )
    text = re.sub(
        r"(?m)^(  required_adapters: )\[\]$",
        r'\1["email"]',
        text,
        count=1,
    )
    path.write_text(text, encoding="utf-8")
    print("邮件发送成功；已启用 email 适配器，并把 TRIP 关键通道设为 email。")
    print("重启 alertd 后生效。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
