# DSH 插件：dsh-plugin-tempguard

把 tempguard 包装成 DeepSeek Harness 插件，让 Agent 可以直接查询温度、检查告警服务、发送测试告警。

插件本身不启动/停止 Python 守护进程，仍然遵循：

```text
dsh-plugin-tempguard → alertd → 适配器 → 微信/QQ/飞书/钉钉/邮件
```

## 目录

```text
dsh-plugin-tempguard/
├─ package.json
├─ cordis.patch.yml       # bundle patch，插入 tempguard 插件行
├─ lib/index.js           # defineTool：tempguard_status / tempguard_alert
├─ locale/zh.json
├─ locale/en.json
├─ icon.svg
└─ README.md
```

## 工具

### `tempguard_status`

读取：

- `alertd` 的 `/health`；
- `logs/temps.csv` 最后一行。

返回示例：

```text
alertd: ok
queue: 0
channels: qq-onebot
latest temp: 2026-10-22 22:18:42,55.5,50.0,55.5,safe,
```

### `tempguard_alert`

发送一条 `INFO` / `WARN` / `TRIP` 告警到 alertd，由 alertd 分发给配置好的适配器。

## 安装到 DSH

```powershell
dsh plugin --profile web add C:\path\to\tempguard\dsh-plugin-tempguard
```

`package.json` 里的 `dsh.bundle.patch` 会自动把插件加入 profile 的 bundles。

然后在 `C:\Users\<you>\.dsh\profiles\web\cordis.patch.yml` 增加配置：

```yaml
- id: tempguard
  config:
    projectDir: "D:\\PythonStudy\\tempguard"
    alertdUrl: "http://127.0.0.1:8765/alert"
    alertdToken: "和 alertd.token 一致"
```

重启 `dsh web` 或在支持 HMR 的环境中等待重载。

## 安全

- `alertdToken` 只放在 profile patch，不提交到 Git；
- 插件只读温度 CSV、POST alertd，不执行 shell，不启动/停止服务；
- 告警服务仍然是本机 `127.0.0.1:8765`。

## 发布到 DSH 插件市场

DSH 的插件市场列表来自 [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) 的 PR，不是本仓库直接提交。发布步骤：

1. 把 `dsh-plugin-tempguard` 发布到 npm（需要 npm 账号）；
2. 在 `awesome-dsh-plugin` 仓库提交一个插件条目 PR；
3. 市场通常一天内自动同步。

本机已经先完成本地安装和工具注册，可在 DSH 里直接用；市场 PR 需要单独的 npm/GitHub 发布权限。
