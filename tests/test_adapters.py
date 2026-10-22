"""适配器离线测试：用本地 mock server 验证请求格式。"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from adapters.astrbot import AstrBotAdapter
from adapters.base import Alert
from adapters.dingtalk import DingTalkAdapter
from adapters.discord import DiscordAdapter
from adapters.feishu import FeishuAdapter
from adapters.qq_onebot import QQOneBotAdapter
from adapters.slack import SlackAdapter
from adapters.telegram import TelegramAdapter
from adapters.wechat_hook import WeChatHookAdapter
from adapters.wechat_ilink import WeChatILinkAdapter
from adapters.wecom import WeComAdapter

ALERT = Alert(
    level="TRIP",
    message="CPU 96.0°C 连续 3 次 ≥ 95°C",
    timestamp="2026-10-22 21:00:00",
    source="test",
)
RECORDS = []


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = raw
        RECORDS.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
            }
        )
        path = urlparse(self.path).path
        if path == "/discord":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/slack":
            payload = b"ok"
        elif path.startswith("/telegram"):
            payload = json.dumps({"ok": True}).encode()
        elif path == "/ilink/bot/sendmessage":
            payload = json.dumps({"ret": 0, "errcode": 0}).encode()
        elif path in ("/send_group_msg", "/send_private_msg"):
            payload = json.dumps({"status": "ok", "retcode": 0}).encode()
        elif path == "/feishu":
            payload = json.dumps({"code": 0}).encode()
        elif path == "/astrbot/api/v1/im/messages":
            payload = json.dumps({"status": "ok"}).encode()
        else:
            payload = json.dumps({"errcode": 0}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def base(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_wecom(self):
        adapter = WeComAdapter("wecom", {"webhook": self.base("/wecom")})
        self.assertTrue(adapter.send(ALERT))
        self.assertEqual(RECORDS[-1]["body"]["msgtype"], "text")
        self.assertIn("CPU 96.0", RECORDS[-1]["body"]["text"]["content"])

    def test_feishu_with_sign(self):
        adapter = FeishuAdapter(
            "feishu",
            {"webhook": self.base("/feishu"), "secret": "test-secret"},
        )
        self.assertTrue(adapter.send(ALERT))
        body = RECORDS[-1]["body"]
        self.assertEqual(body["msg_type"], "text")
        self.assertIn("timestamp", body)
        self.assertIn("sign", body)

    def test_dingtalk_with_sign(self):
        adapter = DingTalkAdapter(
            "dingtalk",
            {"webhook": self.base("/dingtalk"), "secret": "test-secret"},
        )
        self.assertTrue(adapter.send(ALERT))
        query = parse_qs(urlparse(RECORDS[-1]["path"]).query)
        self.assertIn("timestamp", query)
        self.assertIn("sign", query)

    def test_telegram(self):
        adapter = TelegramAdapter(
            "telegram",
            {"bot_token": "123:abc", "chat_id": "456", "api_base": self.base("/telegram")},
        )
        self.assertTrue(adapter.send(ALERT))
        self.assertEqual(RECORDS[-1]["body"]["chat_id"], "456")

    def test_discord(self):
        adapter = DiscordAdapter("discord", {"webhook": self.base("/discord")})
        self.assertTrue(adapter.send(ALERT))
        self.assertIn("CPU 96.0", RECORDS[-1]["body"]["content"])

    def test_slack(self):
        adapter = SlackAdapter("slack", {"webhook": self.base("/slack")})
        self.assertTrue(adapter.send(ALERT))
        self.assertIn("CPU 96.0", RECORDS[-1]["body"]["text"])

    def test_qq_onebot_group(self):
        adapter = QQOneBotAdapter(
            "qq",
            {
                "base_url": self.base(""),
                "target_type": "group",
                "target_id": "123",
                "access_token": "secret",
            },
        )
        self.assertTrue(adapter.send(ALERT))
        self.assertEqual(RECORDS[-1]["body"]["group_id"], "123")
        self.assertEqual(RECORDS[-1]["headers"].get("Authorization"), "Bearer secret")

    def test_wechat_ilink(self):
        adapter = WeChatILinkAdapter(
            "ilink",
            {
                "base_url": self.base(""),
                "bot_token": "token",
                "to_user_id": "user@im.wechat",
                "context_token": "ctx",
            },
        )
        self.assertTrue(adapter.send(ALERT))
        body = RECORDS[-1]["body"]
        self.assertEqual(body["msg"]["to_user_id"], "user@im.wechat")
        self.assertEqual(body["msg"]["item_list"][0]["text_item"]["text"], ALERT.text)

    def test_wechat_hook(self):
        adapter = WeChatHookAdapter("hook", {"url": self.base("/hook")})
        self.assertTrue(adapter.send(ALERT))
        self.assertEqual(RECORDS[-1]["body"]["level"], "TRIP")

    def test_astrbot(self):
        adapter = AstrBotAdapter(
            "astrbot",
            {
                "base_url": self.base("/astrbot"),
                "api_key": "key",
                "umos": ["wechat:FriendMessage:user"],
            },
        )
        self.assertTrue(adapter.send(ALERT))
        self.assertEqual(RECORDS[-1]["body"]["umo"], "wechat:FriendMessage:user")


if __name__ == "__main__":
    unittest.main()
