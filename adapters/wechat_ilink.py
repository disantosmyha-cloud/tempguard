"""个人微信 iLink HTTP 客户端（clean-room 实现，文本消息）。

iLink 是微信侧的机器人 HTTP 接口，不是微信底层 socket 协议。这个适配器
只实现“发文本告警”所需的最小客户端；登录二维码 / 收消息 / 媒体文件
不在告警服务的必需范围内。

需要从微信 iLink 登录流程取得：
- bot_token
- to_user_id
- context_token（对方最近一次会话的上下文 token）
"""

from __future__ import annotations

import base64
import random
import uuid

from .base import Adapter, Alert
from .http import post_json


class WeChatILinkAdapter(Adapter):
    type_name = "wechat_ilink"

    def send(self, alert: Alert) -> bool:
        base_url = str(
            self.config.get("base_url") or "https://ilinkai.weixin.qq.com"
        ).rstrip("/")
        token = str(self.config.get("bot_token") or "").strip()
        to_user = str(self.config.get("to_user_id") or "").strip()
        context_token = str(self.config.get("context_token") or "").strip()
        if not token or not to_user or not context_token:
            return self.mark_error("缺少 bot_token / to_user_id / context_token")

        # 微信 iLink 的请求头：token 类型 + 随机 UIN。
        uin = base64.b64encode(str(random.getrandbits(32)).encode("utf-8")).decode(
            "ascii"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": uin,
        }
        payload = {
            "base_info": {"channel_version": "temguard-alertd"},
            "msg": {
                "from_user_id": "",
                "to_user_id": to_user,
                "client_id": uuid.uuid4().hex,
                "message_type": 2,
                "message_state": 2,
                "context_token": context_token,
                "item_list": [
                    {"type": 1, "text_item": {"text": alert.text[:2000]}}
                ],
            },
        }
        ok, data, error = post_json(
            f"{base_url}/ilink/bot/sendmessage",
            payload,
            timeout=self.timeout(15.0),
            headers=headers,
        )
        if not ok:
            return self.mark_error(error or "HTTP 请求失败")
        if isinstance(data, dict):
            ret = int(data.get("ret", 0) or 0)
            errcode = int(data.get("errcode", 0) or 0)
            if ret == 0 and errcode == 0:
                return self.mark_ok()
            return self.mark_error(
                f"ret={ret} errcode={errcode} errmsg={data.get('errmsg', '')}"
            )
        return self.mark_ok()
