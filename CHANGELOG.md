# Changelog

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
