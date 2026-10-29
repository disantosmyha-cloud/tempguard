# Changelog

## v1.6.1 — 只读温度 API 回归

- 恢复 `GET /temps`（只读，限 loopback，带本机 CORS），供桌宠/状态页读取温度；
- 不恢复任何 `/pet/*` 语音接口，语音仍由独立 `tempguard-voice` 服务提供；
- 新增 `_read_temps` 解析测试。

## v1.6.0 — 语音拆分 / 死手开关接口

- 本地语音/桌宠拆到独立项目 `tempguard-voice`，主仓库不再包含 Pet/CosyVoice/模型/虚拟环境。
- temguard `alertd.py` 恢复为纯告警服务；主仓库工作树恢复干净。
- 新增 `core/deadman.py`：DeadManSwitch 抽象、Null/Mock 实现。
- 新增 `tools/deadman_sim.py`：按回车模拟死手开关触发 TRIP。
- 新增 `docs/死手开关.md`、`docs/语音项目拆分.md`。
- 当前推荐边界：语音是独立 Python 服务；npm 只用于薄 DSH 客户端，不承载模型。

## DSH plugin 0.1.5 — npm 发布

- `dsh-plugin-tempguard@0.1.5` 已发布到 npm。
- `tempguard_status` 修正 `queue` 字段：现在读取 alertd 的 `pending`/`outbox`/`required_adapters`/`config_errors`。
- npm 包补充 repository/homepage/bugs/keywords 元数据。
- `node --test` 通过。

## v1.5.1 — 开源准备

- 文档去个人化：QQ 号、邮箱、本机绝对路径改为占位符。
- 新增 `CONTRIBUTING.md`、`SECURITY.md`、`CODE_OF_CONDUCT.md`。
- 新增 GitHub Issue/PR 模板。
- CI 正式上传并通过：Ruff fatal checks + 35 个测试 + 覆盖率门槛。
- GitHub 仓库补充主题、描述和 CI 徽章。
