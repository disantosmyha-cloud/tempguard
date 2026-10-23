# Security Policy

## Supported versions

安全修复优先提供给最新的 `1.5.x` 版本。

## Reporting

不要公开提交以下内容：

- API key、webhook URL、邮箱授权码；
- `secrets.dat`；
- `config.local.yaml`；
- 含 token 的日志或截图。

请使用 GitHub 仓库的 **Security → Report a vulnerability**（Security Advisory）私下报告，并附上：

- 影响版本；
- 复现步骤；
- 影响范围；
- 建议修复。

## Scope

这个项目是个人温度看门狗，不是安全关键认证系统。它的安全边界包括：

- 本机 loopback HTTP；
- Windows DPAPI 密钥保险箱；
- 告警通道 token；
- 计划任务权限；
- 关机/终止进程动作。

它不承诺：

- 抵御同一 Windows 用户会话内的恶意进程；
- 在断电、断网、系统蓝屏时告警；
- 替代硬件保护、UPS 或外部监控；
- 对所有 CPU/GPU 型号的温度阈值正确。

## Secrets

推荐使用：

```powershell
python -m core.secrets set alertd_token
```

`secrets.dat` 已加入 `.gitignore`。如果误提交，请立即轮换对应 token，并清理 Git 历史。
