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

本机还没有安装 QQ NT / OneBot 桥；GitHub 下载 NapCat/Lagrange 二进制时被网络重置，未能完成二维码登录。

适配器、配置模板和测试已经准备好：

```text
adapters/qq_onebot.py   已实现并通过 mock 测试
config.local.yaml       qq-onebot 模板默认关闭
```

桥接器装好后，把上面配置里的 `enabled` 改成 `true`、填 `target_id`，重启 alertd 即可扫码登录并测试。

## 6. 安全

- `access_token` 只填 `config.local.yaml`；
- OneBot HTTP 只监听 `127.0.0.1`；
- 不要把 OneBot 端口暴露到公网。
