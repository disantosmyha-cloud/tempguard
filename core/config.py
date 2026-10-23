"""配置校验：启动时尽早失败，而不是运行到一半才静默失效。"""

from __future__ import annotations

from typing import Any


class ConfigError(ValueError):
    pass


def _number(section: dict, key: str, default=None):
    value = section.get(key, default)
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{key} 必须是数字，当前是 {value!r}") from exc
    return number


def validate_config(config: Any) -> dict:
    if not isinstance(config, dict):
        raise ConfigError("配置文件顶层必须是 YAML 映射")

    sample = config.get("sample") or {}
    if not isinstance(sample, dict):
        raise ConfigError("sample 必须是映射")
    interval = _number(sample, "interval_seconds", 5)
    if interval is None or interval < 1:
        raise ConfigError("sample.interval_seconds 必须 ≥ 1")

    thresholds = config.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        raise ConfigError("thresholds 必须是映射")
    warning = _number(thresholds, "warning_c", 90)
    terminate = _number(thresholds, "terminate_c", 93)
    shutdown = _number(thresholds, "shutdown_c", 95)
    reset = _number(thresholds, "reset_c", 88)
    if not (reset < warning <= terminate <= shutdown):
        raise ConfigError(
            "thresholds 必须满足 reset_c < warning_c <= terminate_c <= shutdown_c"
        )
    _number(thresholds, "terminate_seconds", 1200)
    samples = _number(thresholds, "shutdown_samples", 3)
    if samples is None or samples < 1:
        raise ConfigError("thresholds.shutdown_samples 必须 ≥ 1")

    safety = config.get("safety") or {}
    if not isinstance(safety, dict):
        raise ConfigError("safety 必须是映射")
    grace = _number(safety, "startup_grace_seconds", 180)
    if grace is None or grace < 0:
        raise ConfigError("safety.startup_grace_seconds 必须 ≥ 0")

    actions = config.get("actions") or {}
    if not isinstance(actions, dict):
        raise ConfigError("actions 必须是映射")
    processes = actions.get("terminate_processes") or []
    if isinstance(processes, str):
        processes = [processes]
    if not isinstance(processes, list):
        raise ConfigError("actions.terminate_processes 必须是列表")

    notify = config.get("notify") or {}
    if not isinstance(notify, dict):
        raise ConfigError("notify 必须是映射")
    mode = str(notify.get("mode") or "direct").strip().lower()
    if mode not in ("direct", "alertd"):
        raise ConfigError("notify.mode 只能是 direct 或 alertd")
    if notify.get("critical_wait_seconds") is not None:
        wait = _number(notify, "critical_wait_seconds", 10)
        if wait is None or wait < 1 or wait > 30:
            raise ConfigError("notify.critical_wait_seconds 必须在 1..30 秒")

    alertd = config.get("alertd") or {}
    if not isinstance(alertd, dict):
        raise ConfigError("alertd 必须是映射")
    port = alertd.get("port", 8765)
    try:
        port_number = int(port)
    except (TypeError, ValueError) as exc:
        raise ConfigError("alertd.port 必须是整数") from exc
    if not 1 <= port_number <= 65535:
        raise ConfigError("alertd.port 必须在 1..65535")
    required_adapters = alertd.get("required_adapters") or []
    if not isinstance(required_adapters, list):
        raise ConfigError("alertd.required_adapters 必须是列表")
    adapters = alertd.get("adapters") or []
    if not isinstance(adapters, list):
        raise ConfigError("alertd.adapters 必须是列表")
    for index, adapter in enumerate(adapters):
        if not isinstance(adapter, dict):
            raise ConfigError(f"alertd.adapters[{index}] 必须是映射")
        if not str(adapter.get("type") or "").strip():
            raise ConfigError(f"alertd.adapters[{index}] 缺少 type")
    return config
