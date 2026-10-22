# QQ 接入（OneBot）

tempguard 不直接实现 QQ 协议，而是通过 OneBot 11 桥接：

```text
temguard → alertd → qq-onebot 适配器 → OneBot HTTP → NapCat / Lagrange → QQ
```

## 1. 选择 QQ 桥

| 桥 | 登录方式 | 说明 |
|---|---|---|
| NapCatQQ | QQ 扫码 | 基于 NTQQ，Windows 常用 |
| Lagrange.OneBot | QQ 扫码 | 独立 .NET 程序 |
| 其他 OneBot 11 实现 | 看实现 | 只要提供 HTTP API 即可 |

当前适配器只要求 OneBot 的 HTTP 发送接口：

```text
POST /send_group_msg    {"group_id":"...","message":"..."}
POST /send_private_msg  {"user_id":"...","message":"..."}
```

## 2. 启动 QQ 桥

以 NapCat 为例：

1. 安装 QQ NT；
2. 安装/解压 NapCat；
3. 启动 NapCat，按提示用手机 QQ 扫码；
4. 在 NapCat 配置里打开 OneBot HTTP 服务，监听 `127.0.0.1:3000`；
5. 确认接口可访问：

```powershell
Invoke-RestMethod http://127.0.0.1:3000/get_login_info
```

如果返回 QQ 号和昵称，说明登录成功。

## 3. 配置 tempguard

编辑 [config.local.yaml](../config.local.yaml)：

```yaml
alertd:
  adapters:
    - name: qq-onebot
      type: qq_onebot
      enabled: true
      base_url: "http://127.0.0.1:3000"
      access_token: ""
      target_type: "private"     # private 或 group
      target_id: "你的QQ号或群号"
      timeout_seconds: 5
```

然后：

```powershell
Stop-ScheduledTask -TaskName alertd
Start-ScheduledTask -TaskName alertd
python main.py --test-notify
```

## 4. 选择目标

- 私聊：`target_type: private`，`target_id` 填接收告警的 QQ 号；
- 群聊：`target_type: group`，`target_id` 填 QQ 群号。

机器人必须在目标群里，或目标 QQ 是机器人的好友。

## 5. 当前环境状态

本机已经完成 QQ 接入：

```text
QQ 9.9.33-52230
NapCat Shell 4.18.41
QQ 号：1356532261（北落师门）
OneBot HTTP：127.0.0.1:3000
快速登录：launcher.bat 1356532261
计划任务：NapCat（登录时启动）
```

tempguard 当前配置：

```yaml
alertd:
  adapters:
    - name: qq-onebot
      type: qq_onebot
      enabled: true
      base_url: "http://127.0.0.1:3000"
      target_type: "private"
      target_id: "1356532261"
```

AstrBot 的告警出口已关闭，但 AstrBot 进程和代码保留，不影响 QQ。

验证：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:3000/get_login_info -ContentType application/json -Body '{}'
python main.py --test-notify
```

最近一次测试结果：

```json
{"name": "qq-onebot", "type": "qq_onebot", "ok": true}
```

如果要把告警发到 QQ 群，把 `target_type` 改成 `group`，`target_id` 填群号，然后重启 alertd。

## 6. 安全

- `access_token` 只填 `config.local.yaml`；
- OneBot HTTP 只监听 `127.0.0.1`；
- 不要把 OneBot 端口暴露到公网。
