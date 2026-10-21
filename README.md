# temguard

**是什么**：一个本地温度看门狗。每隔几秒读一次 CPU/GPU 温度，写进 CSV，温度持续超限就按四态升级：安全 → 警告 → 终止进程 → 关机。

**为什么不是“超一下就杀”**：游戏、编译、瞬时加速都会让温度冲一下。tempguard 只认“连续”：

```text
温度 ≥ 90°C                    → 警告
连续 20 分钟 ≥ 93°C            → 终止进程
连续 3 次 ≥ 95°C               → 关机
温度 < 88°C                    → 恢复正常，所有计时/计数清零
```

> **公开仓库的 `config.yaml` 默认是演习模式（`dry_run: true`）**。本机如果存在 `config.local.yaml`，`main.py` 会优先读取它；当前本机的真实模式参数就在这个文件里，而它已被 `.gitignore` 忽略，不会上传。
>
> 想临时演习：`python main.py --dry-run`；想强制使用公开配置：`python main.py --config config.yaml`。
>
> 目录结构、参数详解、GitHub 开源步骤见 **[docs/使用指南.md](docs/使用指南.md)**。

## 特性

- **四态清晰**：`safe` / `warning` / `terminate` / `shutdown`，主循环按状态动作。
- **只认连续**：瞬时峰值只到警告，掉回阈值以下计时/计数立即重来。
- **演习模式**：所有危险动作都可以先空跑。
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
python main.py               # 正常跑，Ctrl+C 停
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
| `thresholds.warning_c` | 90 | 进入“警告”的温度线（°C） |
| `thresholds.terminate_c` | 93 | 连续达到这个温度才可能终止进程 |
| `thresholds.terminate_seconds` | 1200 | 连续 ≥ `terminate_c` 多少秒才终止（20 分钟） |
| `thresholds.shutdown_c` | 95 | 关机温度线 |
| `thresholds.shutdown_samples` | 3 | 连续多少次 ≥ `shutdown_c` 才关机 |
| `thresholds.reset_c` | 88 | 低于此温度算恢复正常，计时/计数清零 |
| `actions.dry_run` | `true` | 公开默认演习；本机 `config.local.yaml` 里是 `false`（真实模式） |
| `actions.terminate_processes` | `[blender.exe, python.exe]` | 要终止的进程名，不区分大小写 |
| `actions.shutdown_delay_seconds` | 60 | 真关机时留给你的取消时间；取消命令 `shutdown /a` |
| `sensors.cpu` / `sensors.gpu` | `true` | 单独关掉某个温度来源 |
| `notify.print` | `true` | 打印到屏幕 |
| `notify.phone.webhook` | 空 | 以后填手机推送地址即启用；现在留空 |

## 状态与动作

| 状态 | 触发 | main.py 做什么 |
|---|---|---|
| `safe` | 温度正常 | 只写日志；从异常恢复时发一条“恢复正常” |
| `warning` | ≥ `warning_c`，或超温但还没满足连续条件 | 发一条警告（状态变化时才发，不刷屏） |
| `terminate` | 连续 ≥ `terminate_c` 满 `terminate_seconds` | 演习：打印“假装终止了……”；真模式：终止配置的进程 |
| `shutdown` | 连续 `shutdown_samples` 次 ≥ `shutdown_c` | 演习：打印“本该关机”；真模式：`shutdown /s /t 延迟` |

一个都读不到温度时按 `warning` 处理，但不会基于旧数据继续累计计时。

## 传感器支持

| 指标 | 来源（按优先级自动探测） | 读不到时 |
|---|---|---|
| CPU 温度 | LibreHardwareMonitor Web Server（`data.json`）→ `psutil.sensors_temperatures()`（Linux/macOS） | 记空，继续跑 |
| GPU 温度 | `nvidia-smi` → LibreHardwareMonitor（`GPU Core`）→ `pynvml` | 记空，继续跑 |

Windows 上要让 CPU 温度可读，必须让 LibreHardwareMonitor 以管理员身份运行，并开启 **Options → Remote Web Server → Run**。只装了软件但没启动，CPU 一栏会显示“读不到”。NVIDIA 显卡装了驱动就有 `nvidia-smi`；AMD/Intel 显卡的温度由 LibreHardwareMonitor 提供。

## 路线图

- [ ] 手机推送（`core/notify.py` 的 `_push_phone()`，企业微信 / 钉钉 / Server酱 / Bark 任选）
- [ ] 温度曲线图（读 `logs/temps.csv` 画个 SVG）
- [ ] 触发后自动降频而不是终止进程

## 许可证

[MIT](LICENSE) —— 随便用，出事别找我。
