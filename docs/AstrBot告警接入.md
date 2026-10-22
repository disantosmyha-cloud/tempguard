# 通过 AstrBot 接入微信 / QQ / 飞书 / 钉钉 / 国外社交软件

tempguard 不直接对接所有社交平台，而是把告警交给 **AstrBot**，由 AstrBot 用它已经接好的平台适配器转发。

```text
temguard
   │  HTTP POST /api/v1/im/messages
   ▼
AstrBot Open API
   ├─ 微信（weixin_oc）
   ├─ QQ（aiocqhttp / QQ 官方）
   ├─ 飞书（lark）
   ├─ 钉钉（dingtalk）
   ├─ Telegram
   ├─ Discord
   ├─ Slack
   └─ 其他 AstrBot 已配置的平台
```

这样只要 AstrBot 能接的平台，tempguard 都不用改代码；新增平台只是在 AstrBot 里加适配器，再把该会话的 UMO 加到配置里。

> 邮件不走 AstrBot，tempguard 内置了 SMTP 邮件通道，见本文末尾。

---

## 1. 前提

1. AstrBot 已经在运行（本机 Dashboard：`http://127.0.0.1:6185`）；
2. AstrBot 里已经接好了至少一个聊天平台；
3. 在 AstrBot 创建一个 Open API Key。

### 创建 API Key

打开 AstrBot Dashboard：

```text
http://127.0.0.1:6185
```

登录后找到 **API Keys / Open API 密钥**，创建一个 key：

- 名称：`tempguard-alert`
- 权限/Scope：至少勾选 `im`
- 如果需要让 tempguard 自动列会话，再加 `chat`

创建后只显示一次 key，格式类似：

```text
abk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

本机已经创建了一个专用 key（名称 `tempguard-alert`，权限 `im` + `chat`），并写进了 `config.local.yaml`。你可以在 AstrBot Dashboard 里随时吊销它。

---

## 2. 配置 tempguard

编辑 [config.local.yaml](../config.local.yaml)：

```yaml
notify:
  astrbot:
    enabled: true
    base_url: "http://127.0.0.1:6185"
    api_key: "abk_你的key"
    umos:
      - "weixin_personal_mrhg:FriendMessage:o9cq803WfSJKzdYjMy7ENNOPQAWU@im.wechat"
    timeout_seconds: 5
```

- `base_url`：AstrBot Dashboard 地址，不要带 `/api/v1`；
- `api_key`：AstrBot Open API Key；
- `umos`：目标会话列表，可以写多个，一个会话一行；
- `timeout_seconds`：HTTP 超时。

API key 只填 `config.local.yaml`，不要填公开的 `config.yaml`。

---

## 3. UMO 是什么

AstrBot 用 UMO（统一消息来源）标识一个会话，格式：

```text
platform_id:消息类型:session_id
```

例如本机微信：

```text
weixin_personal_mrhg:FriendMessage:o9cq803WfSJKzdYjMy7ENNOPQAWU@im.wechat
```

- `weixin_personal_mrhg`：AstrBot 平台 ID；
- `FriendMessage`：私聊；群聊通常是 `GroupMessage`；
- `o9cq...@im.wechat`：对方的会话 ID。

其他平台同理，例如：

```text
qq_main:FriendMessage:123456789
lark_main:GroupMessage:oc_xxxxxxxx
dingtalk_main:GroupMessage:cidxxxxxxxx
telegram_main:FriendMessage:123456789
discord_main:GroupMessage:123456789
```

实际值以 AstrBot 日志/Dashboard 为准。

---

## 4. 怎么找到其他平台的 UMO

以 QQ 为例：

1. 在 AstrBot 里配置好 QQ 适配器并启动；
2. 用目标 QQ 号给机器人发一条消息；
3. 看 AstrBot 控制台日志，找到类似：

```text
[default] [qq_main(aiocqhttp)] 123456789/123456789: ...
```

4. 对应的 UMO 通常是：

```text
qq_main:FriendMessage:123456789
```

群聊则是：

```text
qq_main:GroupMessage:群号
```

把需要的 UMO 全部加到：

```yaml
umos:
  - "weixin_personal_mrhg:FriendMessage:o9cq...@im.wechat"
  - "qq_main:GroupMessage:123456789"
  - "lark_main:GroupMessage:oc_xxxxxxxx"
```

AstrBot 会逐个发送；某个平台失败不影响其他平台。

> 当前 AstrBot 版本支持微信、QQ、飞书（Lark）、钉钉、Telegram、Discord、Slack、LINE、Mattermost、Misskey 等适配器。具体以你的 AstrBot 插件/适配器版本为准。

---

## 5. 测试

```powershell
cd D:\PythonStudy\tempguard
python main.py --test-notify
```

成功：

```text
测试消息发送成功（至少一个通道）
```

然后检查微信/QQ/飞书/钉钉等目标会话是否收到：

```text
temguard 告警通道测试：如果你收到这条消息，说明配置已经生效。
```

失败时检查：

1. AstrBot 是否在运行；
2. `base_url` 是否正确；
3. API key 是否有效、是否有 `im` 权限；
4. `umos` 是否写对；
5. AstrBot 对应平台是否在线。

---

## 6. 邮件告警

邮件不走 AstrBot，tempguard 直接用 SMTP 发。

以 QQ 邮箱为例：

```yaml
notify:
  email:
    enabled: true
    smtp_host: "smtp.qq.com"
    smtp_port: 465
    use_ssl: true
    starttls: false
    username: "你的QQ邮箱"
    password: "邮箱授权码"       # 不是登录密码
    from_addr: "你的QQ邮箱"
    to_addrs:
      - "收件人@example.com"
    timeout_seconds: 10
```

- QQ 邮箱要在设置里开启 SMTP 服务并生成“授权码”；
- 465 端口通常用 `use_ssl: true`；
- 587 端口通常用 `use_ssl: false` + `starttls: true`；
- 密码只填 `config.local.yaml`。

邮件标题会带 `[temguard][警告]` / `[熔断]`，正文是带时间戳的告警内容。

---

## 7. 企业微信群机器人直连（备用）

如果不想经过 AstrBot，也可以直接用企业微信群机器人 Webhook：

```yaml
notify:
  wechat:
    webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
```

配置见 [微信机器人接入](微信机器人接入.md)。AstrBot 和直连可以同时开，也可以只开一个。

---

## 8. 安全提醒

1. AstrBot API key、邮箱授权码、Webhook 都是密钥，只放 `config.local.yaml`；
2. 公开的 `config.yaml` 里全部保持空字符串；
3. 不要把这些内容发到群里或截图；
4. AstrBot Dashboard 默认监听 `0.0.0.0:6185`，如果只在本人电脑用，建议在 AstrBot 配置里把 `dashboard.host` 改成 `127.0.0.1`；
5. 如果 key 泄露，去 AstrBot Dashboard 吊销 `tempguard-alert`，重新创建并更新配置。

---

## 9. 保护 AstrBot 不被 temguard 误杀

AstrBot 的运行进程也是 `python.exe`。如果 `actions.terminate_processes` 里包含 `python.exe`，温度熔断时可能把 AstrBot 一起杀掉，导致告警发不出去。

tempguard 已经加了保护：

```yaml
actions:
  protect_keywords:
    - astrbot
```

命令行中包含 `astrbot` 的进程不会被终止。即使这样，也建议把 `terminate_processes` 写具体，不要长期用宽泛的 `python.exe`。

---

## 10. 运行顺序

```text
登录 Windows
  → AstrBot 启动（计划任务 AstrBot）
  → temguard 启动（计划任务 temguard）
  → 告警通过 AstrBot Open API 发到微信/QQ/飞书/钉钉/Telegram/Discord…
```

AstrBot 没有启动时，AstrBot 通道会失败，但 temguard 的主循环不会崩；可以直接看 `logs/temps.csv`，或改用企业微信直连/SMTP 邮件作为备用。
