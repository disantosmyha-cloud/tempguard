# Contributing

感谢你愿意改进 temguard。这个项目是 Windows 上的个人温度看门狗，不是安全关键认证系统；提交代码前请先理解它的边界。

## 开发环境

- Windows 10/11
- Python 3.10+
- 可选：LibreHardwareMonitor（读取 CPU/GPU 温度）
- 可选：NVIDIA 驱动自带的 `nvidia-smi`，或 `pynvml`

```powershell
git clone https://github.com/disantosmyha-cloud/tempguard.git
cd tempguard
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

## 测试

```powershell
python -m unittest discover -s tests -v
python -m coverage run -m unittest discover -s tests
python -m coverage report
ruff check --select E9,F63,F7,F82 .
```

Windows 专属测试（DPAPI、单实例锁）在非 Windows 平台会自动跳过。

DSH 插件：

```powershell
npm test --prefix dsh-plugin-tempguard
```

## 本地配置

不要提交：

- `config.local.yaml`
- `secrets.dat`
- `logs/`
- `runtime/`
- 任何 API key、webhook、邮箱授权码、QQ token

配置里的密钥应使用 DPAPI 占位符：

```yaml
token: "${secret:alertd_token}"
```

## 代码原则

- 安全动作宁可失败可见，不要静默吞掉；
- 新增外部平台时必须补失败、超时、重试测试；
- 不要为了“功能多”继续扩大适配器矩阵；
- 传感器、关机、动作重试相关改动需要说明失败模式；
- 文档里的行为必须和代码一致。

## Pull Request

一个 PR 尽量只解决一个问题，并包含：

1. 改动说明和风险；
2. 测试命令与结果；
3. 配置变更；
4. 如果涉及安全动作，写清失败时会发生什么。

## 安全问题

请不要在公开 Issue 里贴 token、授权码或完整配置。  
安全问题请使用 GitHub Security Advisory 私下报告，见 [SECURITY.md](SECURITY.md)。
