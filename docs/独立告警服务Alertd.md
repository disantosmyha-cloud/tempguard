# 独立告警服务 alertd

`alertd.py` 是 tempguard 的独立告警网关。它把“告警接收”和“消息平台协议”拆开：

```text
temguard
   │  POST /alert
   ▼
alertd（独立进程，127.0.0.1:8765）
   ├─ AstrBot Open API → 个人微信 / QQ / 飞书 / 钉钉 / Telegram / Discord / Slack
   ├─ 企业微信群机器人直连
   ├─ SMTP 邮件
   └─ logs/alerts.jsonl（每次发送都留记录）
```

AstrBot 继续作为**协议适配层**，负责各家 IM 的登录、收发和协议变化；alertd 负责接收、排队、重试和分发。这样：

- 不需要自己重写个人微信协议；
- temguard 主循环不直接碰各平台；
- 以后换掉 AstrBot 或增加官方 Webhook，只改 alertd，不改 temguard；
- AstrBot 挂了，alertd 仍可把告警发到企业微信/邮件。

---

## 1. 启动

```powershell
cd D:\PythonStudy\tempguard
python alertd.py
```

后台无窗口运行（本机已注册计划任务）：

```powershell
Start-ScheduledTask -TaskName alertd
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

正常返回：

```json
{
  "status": "ok",
  "queue": 0,
  "channels": ["wecom-group", "feishu", "email"],
  "adapters": [
    {"name": "wecom-group", "type": "wecom", "enabled": true, "last_error": ""}
  ]
}
```

---

## 2. 配置

### 2.1 alertd 服务本身

```yaml
alertd:
  host: "127.0.0.1"
  port: 8765
  token: "本机随机token"
  log_file: logs/alerts.jsonl
  retry_attempts: 3
  retry_backoff_seconds: 2
```

- 只监听 `127.0.0.1`，不要暴露公网；
- `token` 可选，但建议设置；temguard 必须带同样的 token；
- `retry_attempts` / `retry_backoff_seconds` 控制失败重试。

### 2.2 temguard 侧

```yaml
notify:
  mode: alertd
  alertd:
    enabled: true
    url: "http://127.0.0.1:8765/alert"
    token: "和 alertd.token 一致"
    timeout_seconds: 3
```

`mode` 有两个值：

- `direct`：temguard 自己直连 AstrBot/企业微信/邮件（旧行为）；
- `alertd`：temguard 只 POST 到本机 alertd，由 alertd 分发（推荐）。

### 2.3 告警出口

出口在 `alertd.adapters` 里配置，每个适配器独立开关：

```yaml
alertd:
  adapters:
    - name: wecom-group
      type: wecom
      enabled: true
      webhook: "..."
```

支持的 `type`：

```text
wecom / feishu / dingtalk / telegram / discord / slack / email
qq_onebot / wechat_ilink / wechat_hook / astrbot
```

每个平台的字段、限制和示例见 [告警适配器](告警适配器.md)。

兼容旧配置：

- `notify.astrbot` → 自动变成 `astrbot-legacy`
- `notify.wechat` → 自动变成 `wecom-legacy`
- `notify.email` → 自动变成 `email-legacy`

如果 `alertd.adapters` 里显式启用了同类型适配器，旧配置不会重复加载。

---

## 3. API 契约

### 发送告警

```http
POST /alert
Content-Type: application/json
X-Alert-Token: 本机token

{
  "level": "TRIP",
  "message": "CPU 96.0°C 连续 3 次 ≥ 95°C",
  "source": "temguard"
}
```

返回：

```json
{"status":"accepted"}
```

- `level`：`INFO` / `WARN` / `TRIP`；
- `source`：来源标识，默认 `temguard`；
- alertd 立即返回 202，实际发送由后台 worker 完成；
- 队列满时返回 503。

### 健康检查

```http
GET /health
```

返回队列长度和当前启用的出口。

---

## 4. 日志

```text
logs/alerts.jsonl
```

每行一条 JSON：

```json
{"time":"2026-10-22 21:29:41","level":"INFO","source":"temguard","message":"temguard 启动...","ok":true,"attempts":1,"results":[{"name":"wecom-group","type":"wecom","ok":true,"attempts":1,"error":""}]}
```

- `ok`：是否至少有一个出口发送成功；
- `attempts`：所有适配器里最大的尝试次数；
- `results`：每个适配器的结果和最近错误；
- 文件超过 5MB 会自动轮转为 `alerts.jsonl.1`。

`logs/*.jsonl` 已被 `.gitignore` 忽略，不会上传 GitHub。

---

## 5. 开机自启

本机已注册三个计划任务：

```text
AstrBot   → 登录时启动（协议层）
alertd    → 登录时启动（独立告警服务）
temguard  → 登录时启动（温度监控）
```

查看状态：

```powershell
Get-ScheduledTask -TaskName AstrBot,alertd,temguard | Select TaskName,State
```

启动/停止 alertd：

```powershell
Start-ScheduledTask -TaskName alertd
Stop-ScheduledTask -TaskName alertd
```

---

## 6. 为什么不让 temguard 直接调 AstrBot

- AstrBot 的网络/协议可能卡顿或重启，直接调用会拖慢主循环；
- alertd 有队列、重试、超时和日志，失败不会丢在主循环里；
- 多个出口（企业微信/邮件）可以并行分发；
- 以后换 QQ/飞书/钉钉/Telegram 只需要改 alertd 配置，temguard 完全不动；
- AstrBot 仍是协议层，不重写个人微信协议。

---

## 7. 故障排查

### `/health` 打不开

```powershell
Get-ScheduledTask -TaskName alertd
Get-Process pythonw
```

看 `logs/alerts.jsonl` 是否有记录，或手动前台运行：

```powershell
python alertd.py
```

### 返回 401

`notify.alertd.token` 和 `alertd.token` 不一致。

### 返回 503

队列满，通常是下游平台长时间超时；检查 AstrBot/邮件服务器。

### 日志里 `ok: false`

说明所有出口都失败：

1. AstrBot 是否在运行；
2. API key 是否有效；
3. UMO 是否正确；
4. 邮件服务器是否可达。

### AstrBot 被温度熔断杀掉

`actions.protect_keywords` 已经包含：

```yaml
protect_keywords:
  - astrbot
  - alertd
```

命令行含这些词的进程不会终止。
