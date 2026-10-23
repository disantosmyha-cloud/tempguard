# Changelog

## v1.5.0 — 安全语义与工程化

- 传感器新鲜度检测：全部传感器失效持续 `sensor_loss_seconds` 后按 `sensor_loss_action` 执行 fail-safe。
- 关键动作日志：terminate/shutdown 失败后按 `actions.retry_seconds` 重试，跨进程恢复。
- 熔断计时器持久化：同一启动周期重启不再重置 20 分钟终止计时。
- 可选外部 heartbeat：配置 `monitor.heartbeat_url` 后可由外部 dead-man switch 发现整机失联。
- alertd：`required_adapters` 启动校验（不匹配时 health=degraded）、幂等键、wait 跨 outbox 重试。
- 适配器熔断器和重试抖动。
- `pyproject.toml`、依赖版本边界、覆盖率测量；测试增至 35 个。
- DSH 插件增加 `node --test` 测试和导出 `asConfig`。

## v1.4.1 — 官方邮件通道

- QQ 邮箱 `your-qq@qq.com` 已启用 SMTP 授权码并存入 DPAPI。
- `email` 与 `qq-onebot` 双通道；`TRIP` 必须由 email 确认。
- 已用 IMAP 验证测试邮件真实到达。
- `required_adapters` 增加配置类型校验。

## v1.4.0 — 生产前基线

- outbox 失败自动退避重试（`max_attempts`）。
- 关键告警可配置 `required_adapters`，TRIP 必须由指定官方通道确认。
- 本地失败兜底：网络全挂时蜂鸣 + `logs/critical-alerts.log`。
- Windows DPAPI `secrets.dat`；配置支持 `${secret:name}` 占位符。
- CSV/outbox 保留策略。
- 21 个单元测试。

## v1.3.1 — 失败告警重试

- `POST /retry` 将 `failed` 告警重新放回 outbox。
- 健康检查继续暴露最近失败，便于通道恢复后补发。

## v1.3.0 — 可靠性硬化

- alertd 使用 SQLite 持久化 outbox；进程重启不丢 pending 告警。
- TRIP/WARN/INFO 优先级队列；worker 数量可配，慢通道不再完全阻塞关键告警。
- 适配器并行 fanout，单个通道超时不影响其他通道。
- `POST /alert` 支持 `wait: true`，返回真实投递结果。
- 关机/终止进程前同步等待告警确认（`notify.critical_wait_seconds`，默认 10 秒）。
- 启动保护只在冷启动生效；同一 Windows 启动周期内重启不再获得 180 秒免动作窗口。
- temguard/alertd 增加文件锁，防止重复进程。
- 启动配置校验；非法阈值/端口/mode 直接失败。
- AstrBot Dashboard、NapCat WebUI、alertd 统一绑定 `127.0.0.1`。
- 新增单元测试：熔断冷启动、outbox 优先级、持久化、配置校验、alertd 等待投递。
- 新增 GitHub Actions Python 测试。

## v1.2.0 — QQ 告警通道

- NapCat 4.18.41 + QQ 9.9.33 快速登录。
- OneBot HTTP `127.0.0.1:3000`，alertd 切换到 `qq-onebot`。
- AstrBot 保留但不再作为告警出口。

## v1.1.0 — DSH 插件

- 新增 `dsh-plugin-tempguard`：`tempguard_status` / `tempguard_alert`。
- 本地 web profile 安装并验证。
- 提交 awesome-dsh-plugin 目录 PR。

## v1.0.5 — 适配器层

- 企业微信、飞书、钉钉、Telegram、Discord、Slack、邮件、QQ OneBot、iLink、微信桥。
