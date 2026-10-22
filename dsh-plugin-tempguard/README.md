# dsh-plugin-tempguard

DeepSeek Harness plugin exposing two tools backed by the local tempguard watchdog:

- `tempguard_status` — read `alertd` health and the latest temperature CSV row;
- `tempguard_alert` — send an INFO/WARN/TRIP alert through `alertd` to the configured adapters.

It does **not** start or stop the watchdog; the Python services remain independent.

## Install locally

From the profile directory:

```powershell
dsh plugin --profile web add D:\PythonStudy\tempguard\dsh-plugin-tempguard
```

Then add a loader entry to the profile patch (`cordis.patch.yml`):

```yaml
- id: tempguard
  name: "dsh-plugin-tempguard"
  config:
    projectDir: "D:\\PythonStudy\\tempguard"
    alertdUrl: "http://127.0.0.1:8765/alert"
    alertdToken: "same token as alertd"
```

Restart `dsh web` (or enable HMR) and the tools appear.

## Security

`alertdToken` is a local secret; keep it in the profile patch, not in this README or Git.
