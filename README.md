# temguard

**是什么**：一个本地温度看门狗。每隔几秒读一次 CPU/GPU 温度，写进 CSV，温度持续超限就按四态升级：安全 → 警告 → 终止进程 → 关机。

**为什么不是“超一下就杀”**：游戏、编译、瞬时加速都会让温度冲一下。tempguard 只认“连续”：

```text
温度 ≥ 90°C                    → 警告
连续 20 分钟 ≥ 93°C            → 终止进程
连续 3 次 ≥ 95°C               → 关机
温度 < 88°C                    → 恢复正常，所有计时/计数清零

启动后 180 秒内、且还没读到正常温度前：只警告，不终止、不关机
```

> **公开仓库的 `config.yaml` 默认是演习模式（`dry_run: true`）**。本机如果存在 `config.local.yaml`，`main.py` 会优先读取它；当前本机的真实模式参数就在这个文件里，而它已被 `.gitignore` 忽略，不会上传。
>
> 想临时演习：`python main.py --dry-run`；想强制使用公开配置：`python main.py --config config.yaml`。
>
> 目录结构、参数详解、GitHub 开源步骤见 **[docs/使用指南.md](docs/使用指南.md)**。

## 特性

- **四态清晰**：`safe` / `warning` / `terminate` / `shutdown`，主循环按状态动作。
- **只认连续**：瞬时峰值只到警告，掉回阈值以下计时/计数立即重来。
- **开机保护**：启动后 180 秒内、且未读到正常温度前，即使传感器报 100°C+ 也只警告，不会直接关机。
- **演习模式**：所有危险动作都可以先空跑。
- **多平台告警**：通过 AstrBot Open API 转发到微信/QQ/飞书/钉钉/Telegram/Discord/Slack；也支持企业微信直连和 SMTP 邮件。
- **独立告警服务**：temguard → alertd → 可插拔适配器，带 SQLite 持久化 outbox、TRIP 优先级、并行 fanout、重试、健康检查和发送日志。
- **关键动作等待送达**：关机/终止进程前同步等待告警确认（默认 10 秒），避免“告警还没发出去就关机”。
- **官方平台适配器**：企业微信、飞书、钉钉、Telegram、Discord、Slack、SMTP 邮件、QQ OneBot、个人微信 iLink、Wechaty/WeChatFerry 桥，全部不依赖 AstrBot。
- **DSH 插件**：`dsh-plugin-tempguard` 把温度查询和告警发送注册成 Agent 工具，可在 DeepSeek Harness 里直接调用。
- **读不到不崩**：传感器缺失记为 `None`，主循环照常跑。
- **单轮错误保护**：采样、写日志、发通知哪一步出错，打印后继续下一轮。
- **日志即证据**：每次采样一行 CSV，事后能回看温度、状态和原因。

## 安装

```powershell
git clone <你的仓库地址> temguard
cd temguard
pip install -r requirements.txt
```

核心依赖只有 `pyyaml` + `psutil`。

### Windows 读 CPU 温度：LibreHardwareMonitor

Windows 自带的 ACPI/WMI 温度经常读不到，或者不是 CPU 核心温度。tempguard 读取 LibreHardwareMonitor 的 **Remote Web Server** JSON：

1. 到 [LibreHardwareMonitor Releases](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases) 下载 zip 并解压。
2. 以**管理员身份**运行 `LibreHardwareMonitor.exe`，保持它开着。
3. 打开 **Options → Remote Web Server → Run**。
4. 长期挂机再勾选 **Options → Run On Windows Startup** 和 **Start Minimized**。

默认地址是 `http://127.0.0.1:8085/data.json`。如果改过端口，设置环境变量 `TEMPGUARD_LHM_URL` 即可，不用改代码。LHM 的 Authentication 保持关闭（只监听 127.0.0.1 就够安全），否则 sensors.py 不会携带登录凭据。

> LHM 0.9.6 已经不再发布传感器 WMI 命名空间，所以这里走本机 HTTP，不需要安装 Python 的 `wmi` 包。LHM 没启动或没开 Web Server 时，CPU 一栏返回 `None`，不会报错。

可选增强：

```powershell
pip install pynvml    # 没有 nvidia-smi 命令时读 GPU 温度
```

## 快速开始

```powershell
python core\sensors.py       # 单独检查 CPU/GPU 温度
python core\fuse.py          # 看四态熔断的假数据演示
python main.py --once        # 只检查一次，确认配置和传感器
python main.py --dry-run     # 强制演习模式跑循环
python main.py               # 正常跑，Ctrl+C 停（会打开黑窗口）
```

### 多平台告警（AstrBot）

AstrBot 已经接好的微信/QQ/飞书/钉钉/Telegram/Discord/Slack 等平台，都可以作为 tempguard 的告警出口：

```yaml
notify:
  astrbot:
    enabled: true
    base_url: "http://127.0.0.1:6185"
    api_key: "abk_你的key"        # 只填 config.local.yaml
    umos:
      - "weixin_personal_mrhg:FriendMessage:o9cq...@im.wechat"
      - "qq_main:GroupMessage:123456789"
    timeout_seconds: 5
```

### 独立告警服务 alertd

推荐架构：

```text
temguard → alertd (127.0.0.1:8765) → AstrBot → 微信/QQ/飞书/钉钉/Telegram/Discord
                                   → 企业微信直连
                                   → SMTP 邮件
```

`alertd` 是独立进程，负责接收、排队、重试、日志和分发；AstrBot 只做协议层。这样 AstrBot 或某个平台出问题，不会拖住 temguard 主循环。

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

本机已注册四个计划任务：`AstrBot`（保留备用）、`NapCat`（QQ 协议层）、`alertd`、`temguard`。`NapCat` 使用 supervisor 自动拉起；`alertd`/`temguard` 有文件锁和失败重启。

AstrBot、NapCat、alertd 都只监听 `127.0.0.1`；不要把 Dashboard/WebUI 暴露到公网。

密钥用 Windows DPAPI 保存到 `secrets.dat`，配置里只写占位符：

```yaml
token: "${secret:alertd_token}"
```

管理：

```powershell
python -m core.secrets set alertd_token
python -m core.secrets list
```

QQ 邮箱 SMTP 一步配置（需要先在 QQ 邮箱开启 SMTP 并生成授权码）：

```powershell
python tools/setup_email.py
```

它只在邮件测试成功后启用 email，并把 `TRIP` 的关键通道设为 email。

DPAPI 只能由当前 Windows 用户解密；`secrets.dat` 已被 `.gitignore` 忽略。

完整说明见 [docs/独立告警服务Alertd.md](docs/独立告警服务Alertd.md)。

### 可插拔适配器

`alertd.adapters` 里按类型配置，全部独立开关：

```text
wecom / feishu / dingtalk / telegram / discord / slack / email
qq_onebot / wechat_ilink / wechat_hook / astrbot
```

每个平台的配置示例、加签方式和个人微信 iLink 的上下文限制见 [docs/告警适配器.md](docs/告警适配器.md)。QQ 扫码登录和 OneBot 桥见 [docs/QQ接入.md](docs/QQ接入.md)。

### DSH 插件

`dsh-plugin-tempguard` 已注册两个工具：

- `tempguard_status`：读取 alertd 健康状态和最新温度；
- `tempguard_alert`：通过 alertd 发送告警。

安装和配置见 [docs/DSH插件.md](docs/DSH插件.md)。本机 web profile 已安装；插件市场发布需要 npm 账号和 awesome-dsh-plugin PR。

### 测试所有告警通道

```powershell
python main.py --test-notify
```

安全故障演练（不会加热硬件、不会关机/杀进程）：

```powershell
python tools/fault_drill.py
```

AstrBot 平台配置见 [docs/AstrBot告警接入.md](docs/AstrBot告警接入.md)，包括怎么找 QQ/飞书/钉钉/Telegram 的 UMO、怎么接 SMTP 邮件，以及怎么保护 AstrBot 不被熔断误杀。

如果不想经过 AstrBot，也可以直接用企业微信群机器人：

```yaml
notify:
  wechat:
    webhook: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"
```

见 [docs/微信机器人接入.md](docs/微信机器人接入.md)。公开的 `config.yaml` 里 API key、Webhook、邮箱密码全部保持空字符串。

### 后台运行（无黑窗口）

`python main.py` 是前台运行，关掉控制台就会停止。想挂机又不想留着黑窗口，可以用 `pythonw.exe` 或计划任务后台运行；本机已经创建了 `temguard` 计划任务，登录时自动启动，无控制台窗口。

查看是否在跑：

```powershell
Get-Process pythonw
Get-Content logs/temps.csv -Tail 5
```

停止/启动后台任务：

```powershell
Stop-ScheduledTask -TaskName temguard
Start-ScheduledTask -TaskName temguard
```

启动后会看到：

```text
[信息] temguard 启动：每 5s 检查一次，警告线 90°C，连续 20 分钟 ≥ 93°C 终止进程，连续 3 次 ≥ 95°C 关机；演习模式（不真动手）
[警告] 温度警告：CPU 91.0°C ≥ 警告线 90°C
[熔断] 持续高温，终止进程。CPU 94.0°C 已连续 1200s ≥ 93°C
[信息] 演习：假装终止了 blender.exe(48368)
[熔断] 危险高温，需要关机。CPU 96.0°C 连续 3 次 ≥ 95°C
[警告] 演习：本该在 60s 后关机，已跳过（不会执行 shutdown）
```

本机真实模式（`config.local.yaml` 里 `dry_run: false`）会把上面的“演习”换成真实终止/真实关机。

控制台只在状态变化时打印（警告、恢复、终止、关机），温度正常时保持安静，减少无谓输出；每 5 秒的采样仍然会写进日志。

日志在 `logs/temps.csv`，列为：

```text
time,cpu,gpu,hottest,state,reason
```

- `hottest`：CPU/GPU 中最热的温度；
- `state`：四态之一；
- `reason`：本轮判断原因，正常时为空。

旧表头不匹配时会自动改名备份成 `temps.legacy-时间.csv`。

## 配置

全部在 [config.yaml](config.yaml)，改完重启即可，不用动代码。

| 键 | 默认 | 说明 |
|---|---|---|
| `sample.interval_seconds` | 5 | 检查间隔（秒） |
| `sample.log_file` | `logs/temps.csv` | 温度日志路径 |
| `sample.max_log_bytes` | 20MB | CSV 超过后自动轮转 |
| `thresholds.warning_c` | 90 | 进入“警告”的温度线（°C） |
| `thresholds.terminate_c` | 93 | 连续达到这个温度才可能终止进程 |
| `thresholds.terminate_seconds` | 1200 | 连续 ≥ `terminate_c` 多少秒才终止（20 分钟） |
| `thresholds.shutdown_c` | 95 | 关机温度线 |
| `thresholds.shutdown_samples` | 3 | 连续多少次 ≥ `shutdown_c` 才关机 |
| `thresholds.reset_c` | 88 | 低于此温度算恢复正常，计时/计数清零 |
| `safety.startup_grace_seconds` | 180 | 启动后多少秒内只警告、不终止/关机 |
| `safety.require_cool_baseline` | `true` | 是否必须先读到一次正常温度才允许动作 |
| `actions.dry_run` | `true` | 公开默认演习；本机 `config.local.yaml` 里是 `false`（真实模式） |
| `actions.terminate_processes` | `[blender.exe, python.exe]` | 要终止的进程名，不区分大小写 |
| `actions.shutdown_delay_seconds` | 60 | 真关机时留给你的取消时间；取消命令 `shutdown /a` |
| `actions.protect_keywords` | `[astrbot, alertd]` | 命令行包含这些词的进程不会被终止，保护告警服务 |
| `sensors.cpu` / `sensors.gpu` | `true` | 单独关掉某个温度来源 |
| `alertd.host` / `alertd.port` | `127.0.0.1` / 8765 | 独立告警服务监听地址 |
| `alertd.token` | 空 | alertd 的本机鉴权 token |
| `alertd.db_file` | `logs/alerts.db` | SQLite 持久化 outbox |
| `alertd.workers` | 2 | worker 数量，避免单个慢通道堵死优先级告警 |
| `alertd.max_pending` | 1000 | outbox 上限 |
| `alertd.retention_days` | 30 | 已投递/失败记录保留天数 |
| `alertd.max_history` | 10000 | 最多保留多少条历史记录 |
| `alertd.retry_attempts` | 3 | 每个适配器独立重试次数 |
| `alertd.max_attempts` | 3 | outbox 整体投递轮数（失败退避重试） |
| `alertd.required_adapters` | `[]` | TRIP 必须成功的适配器名，例如 `["email"]` |
| `alertd.adapters` | 全部关闭的模板 | 可插拔告警出口，按 `type` 选择平台 |
| `notify.mode` | `direct` | `direct`=temguard 自己发；`alertd`=投递给独立服务 |
| `notify.critical_wait_seconds` | 10 | 关机/终止进程前等待告警确认的秒数 |
| `notify.alertd.enabled` | `false` | 是否启用 alertd 模式 |
| `notify.alertd.url` | `http://127.0.0.1:8765/alert` | alertd 接收地址 |
| `notify.print` | `true` | 打印到屏幕 |
| `notify.astrbot.enabled` | `false` | 是否通过 AstrBot 转发 |
| `notify.astrbot.base_url` | `http://127.0.0.1:6185` | AstrBot Dashboard 地址 |
| `notify.astrbot.api_key` | 空 | AstrBot Open API Key；只填 `config.local.yaml` |
| `notify.astrbot.umos` | `[]` | 目标会话列表，可同时写微信/QQ/飞书/钉钉等 |
| `notify.astrbot.timeout_seconds` | 5 | AstrBot 请求超时 |
| `notify.email.enabled` | `false` | 是否发 SMTP 邮件 |
| `notify.email.smtp_host` / `smtp_port` | 空 / 465 | 邮件服务器 |
| `notify.email.username` / `password` | 空 | 邮箱账号 / 授权码，只填本地配置 |
| `notify.email.from_addr` / `to_addrs` | 空 / `[]` | 发件人 / 收件人列表 |
| `notify.wechat.webhook` | 空 | 企业微信群机器人 Webhook；只填 `config.local.yaml` |
| `notify.wechat.mentioned_list` | `[]` | 可选 @ 人，例如 `["@all"]` |
| `notify.wechat.mentioned_mobile_list` | `[]` | 可选 @ 手机号 |
| `notify.wechat.timeout_seconds` | 5 | 微信请求超时（秒） |

## 状态与动作

| 状态 | 触发 | main.py 做什么 |
|---|---|---|
| `safe` | 温度正常 | 只写日志；从异常恢复时发一条“恢复正常” |
| `warning` | ≥ `warning_c`，或超温但还没满足连续条件 | 发一条警告（状态变化时才发，不刷屏） |
| `terminate` | 连续 ≥ `terminate_c` 满 `terminate_seconds` | 演习：打印“假装终止了……”；真模式：终止配置的进程 |
| `shutdown` | 连续 `shutdown_samples` 次 ≥ `shutdown_c` | 演习：打印“本该关机”；真模式：`shutdown /s /t 延迟` |

一个都读不到温度时按 `warning` 处理，但不会基于旧数据继续累计计时。

### 开机保护

LHM/驱动刚启动时，传感器偶尔会报出 100°C+ 的假高温。直接按这个温度关机显然不科学，所以 fuse 有两道保护：

1. **启动保护期**：程序启动后 `startup_grace_seconds`（默认 180 秒）内，只警告，不终止、不关机；
2. **正常温度基线**：必须先读到一次低于 `warning_c` 的温度，才允许执行动作。如果开机后一直只读到异常高温，就一直只警告。

保护期结束时，保护期内累计的高温次数/时长会清零，不会“带着开机那几分钟的假数据”立刻关机。

## 传感器支持

| 指标 | 来源（按优先级自动探测） | 读不到时 |
|---|---|---|
| CPU 温度 | LibreHardwareMonitor Web Server（`data.json`）→ `psutil.sensors_temperatures()`（Linux/macOS） | 记空，继续跑 |
| GPU 温度 | `nvidia-smi` → LibreHardwareMonitor（`GPU Core`）→ `pynvml` | 记空，继续跑 |

Windows 上要让 CPU 温度可读，必须让 LibreHardwareMonitor 以管理员身份运行，并开启 **Options → Remote Web Server → Run**。只装了软件但没启动，CPU 一栏会显示“读不到”。NVIDIA 显卡装了驱动就有 `nvidia-smi`；AMD/Intel 显卡的温度由 LibreHardwareMonitor 提供。

## 路线图

- [x] 企业微信群机器人告警（见 [docs/微信机器人接入.md](docs/微信机器人接入.md)）
- [x] AstrBot 多平台告警：微信/QQ/飞书/钉钉/Telegram/Discord 等（见 [docs/AstrBot告警接入.md](docs/AstrBot告警接入.md)）
- [x] 独立 alertd + 可插拔适配器：企业微信/飞书/钉钉/Telegram/Discord/Slack/邮件/QQ OneBot/微信桥（见 [docs/告警适配器.md](docs/告警适配器.md)）
- [x] 个人微信 iLink clean-room 客户端（实验性，受 context_token 限制）
- [ ] 温度曲线图（读 `logs/temps.csv` 画个 SVG）
- [ ] 触发后自动降频而不是终止进程

## 许可证

[MIT](LICENSE) —— 随便用，出事别找我。
