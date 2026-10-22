"""根据配置构建适配器列表。"""

from __future__ import annotations

from typing import Any, Optional

from .astrbot import AstrBotAdapter
from .base import Adapter
from .dingtalk import DingTalkAdapter
from .discord import DiscordAdapter
from .email import EmailAdapter
from .feishu import FeishuAdapter
from .qq_onebot import QQOneBotAdapter
from .slack import SlackAdapter
from .telegram import TelegramAdapter
from .wechat_hook import WeChatHookAdapter
from .wechat_ilink import WeChatILinkAdapter
from .wecom import WeComAdapter


class UnknownAdapter(Adapter):
    type_name = "unknown"

    def send(self, alert):
        return self.mark_error(f"未知适配器类型: {self.config.get('type', '')}")


TYPE_MAP = {
    "wecom": WeComAdapter,
    "wechat_work": WeComAdapter,
    "企业微信": WeComAdapter,
    "feishu": FeishuAdapter,
    "lark": FeishuAdapter,
    "飞书": FeishuAdapter,
    "dingtalk": DingTalkAdapter,
    "ding": DingTalkAdapter,
    "钉钉": DingTalkAdapter,
    "telegram": TelegramAdapter,
    "tg": TelegramAdapter,
    "discord": DiscordAdapter,
    "slack": SlackAdapter,
    "email": EmailAdapter,
    "smtp": EmailAdapter,
    "邮件": EmailAdapter,
    "qq_onebot": QQOneBotAdapter,
    "onebot": QQOneBotAdapter,
    "qq": QQOneBotAdapter,
    "wechat_ilink": WeChatILinkAdapter,
    "ilink": WeChatILinkAdapter,
    "wechat_hook": WeChatHookAdapter,
    "wechaty": WeChatHookAdapter,
    "wechatferry": WeChatHookAdapter,
    "hook": WeChatHookAdapter,
    "astrbot": AstrBotAdapter,
}


def _unique_name(base: str, used: set[str]) -> str:
    name = base
    index = 2
    while name in used:
        name = f"{base}-{index}"
        index += 1
    used.add(name)
    return name


def build_adapters(config: dict) -> list[Adapter]:
    alertd = config.get("alertd") or {}
    notify = config.get("notify") or {}
    entries = alertd.get("adapters") or []
    if not isinstance(entries, list):
        entries = []

    adapters: list[Adapter] = []
    used_names: set[str] = set()
    explicit_types: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        type_name = str(entry.get("type") or "").strip().lower()
        if not type_name:
            continue
        if entry.get("enabled", True):
            explicit_types.add(type_name)
        cls = TYPE_MAP.get(type_name, UnknownAdapter)
        name = _unique_name(
            str(entry.get("name") or type_name),
            used_names,
        )
        adapters.append(cls(name, dict(entry)))

    # 兼容现有 notify.* 配置：没有显式启用同类型适配器时，自动加载旧配置。
    def add_legacy(adapter: Adapter, type_name: str) -> None:
        if type_name in explicit_types:
            return
        adapters.append(adapter)

    astrbot = notify.get("astrbot") or {}
    if (
        astrbot.get("enabled")
        and astrbot.get("api_key")
        and astrbot.get("umos")
    ):
        add_legacy(
            AstrBotAdapter("astrbot-legacy", dict(astrbot)),
            "astrbot",
        )

    wechat = notify.get("wechat") or {}
    webhook = str(
        wechat.get("webhook") or (notify.get("phone") or {}).get("webhook") or ""
    ).strip()
    if webhook:
        legacy_wecom = dict(wechat)
        legacy_wecom["webhook"] = webhook
        add_legacy(WeComAdapter("wecom-legacy", legacy_wecom), "wecom")

    email = notify.get("email") or {}
    if email.get("enabled") and email.get("smtp_host") and email.get("to_addrs"):
        add_legacy(EmailAdapter("email-legacy", dict(email)), "email")

    return adapters
