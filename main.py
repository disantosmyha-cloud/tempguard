"""大门：主循环。

每隔配置的秒数：读温度 → 写 CSV → 问 fuse 四态 → 该告警就告警。
fuse 说“终止进程”时，演习模式只打印，非演习模式才真杀；
fuse 说“关机”时同理，演习模式绝不执行 shutdown。

整个循环有错误保护：单轮出错打印一下继续跑，按 Ctrl+C 干净退出。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from core import action_journal as action_journal_mod
from core import fuse as fuse_mod
from core import heartbeat as heartbeat_mod
from core import notify as notify_mod
from core import sensors
from core.config import validate_config
from core.secrets import resolve_config
from core.single_instance import AlreadyRunning, InstanceLock

try:
    import psutil
except Exception:
    psutil = None

ROOT = Path(__file__).resolve().parent
CSV_HEADER = ["time", "cpu", "gpu", "hottest", "state", "reason"]


# ---------------------------------------------------------------- 配置 / 日志

def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return validate_config(resolve_config(yaml.safe_load(fh) or {}))


def _default_config_path() -> Path:
    """本机有 config.local.yaml 就优先用它；公开仓库只有 config.yaml。"""
    local = ROOT / "config.local.yaml"
    return local if local.exists() else ROOT / "config.yaml"


def _open_log(path: Path, max_bytes: int = 20 * 1024 * 1024):
    """追加打开 CSV；超大文件/旧表头会自动改名备份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists() or path.stat().st_size == 0

    if not fresh and path.stat().st_size > max(1024 * 1024, int(max_bytes)):
        backup = path.with_name(
            f"{path.stem}.{dt.datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
        )
        try:
            path.replace(backup)
            fresh = True
        except Exception:
            pass

    if not fresh:
        try:
            with open(path, "r", encoding="utf-8") as check:
                old_header = check.readline().strip().split(",")
            if old_header != CSV_HEADER:
                backup = path.with_name(
                    f"{path.stem}.legacy-{dt.datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
                )
                path.replace(backup)
                fresh = True
        except Exception:
            pass  # 文件被占用时保持原样，不要影响守护进程启动

    fh = open(path, "a", newline="", encoding="utf-8")
    writer = csv.writer(fh)
    if fresh:
        writer.writerow(CSV_HEADER)
    return fh, writer


def _fmt(value: Optional[float]) -> str:
    return "" if value is None else f"{value:.1f}"


# ---------------------------------------------------------------- 进程处理

def _protected_pids() -> set:
    """自己和自己所有父进程一律不杀。"""
    protected = {os.getpid()}
    if psutil is None:
        return protected
    try:
        me = psutil.Process()
        protected = {me.pid}
        protected.update(parent.pid for parent in me.parents())
    except Exception:
        pass
    return protected


def _find_processes(
    names: List[str],
    protect_keywords: Optional[List[str]] = None,
) -> List[Tuple[str, int]]:
    targets = {
        str(name).strip().lower()
        for name in (names or [])
        if str(name).strip()
    }
    if not targets or psutil is None:
        return []

    keywords = [
        str(word).strip().lower()
        for word in (protect_keywords or [])
        if str(word).strip()
    ]
    protected = _protected_pids()
    matches: List[Tuple[str, int]] = []
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                info = proc.info or {}
                pid = info.get("pid")
                name = str(info.get("name") or "")
                if pid in protected or not name:
                    continue
                cmdline = " ".join(info.get("cmdline") or []).lower()
                if any(word in cmdline for word in keywords):
                    continue
                if name.lower() in targets:
                    matches.append((name, int(pid)))
            except Exception:
                continue
    except Exception:
        pass
    return matches


def _local_critical_fallback(message: str) -> None:
    """网络全挂时至少让本机响一声并留下本地记录。"""
    try:
        if os.name == "nt":
            import winsound

            winsound.MessageBeep(winsound.MB_ICONHAND)
    except Exception:
        pass
    try:
        path = ROOT / "logs" / "critical-alerts.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except Exception:
        pass


def _critical_wait_seconds(config: dict) -> float:
    cfg = (config.get("notify") or {}).get("critical_wait_seconds", 10)
    try:
        value = float(cfg)
    except (TypeError, ValueError):
        value = 10.0
    return max(1.0, min(30.0, value))


def _handle_terminate(decision: fuse_mod.Decision, config: dict) -> bool:
    """处理“终止进程”状态。"""
    actions = config.get("actions") or {}
    names = actions.get("terminate_processes") or []
    if isinstance(names, str):
        names = [names]
    dry_run = bool(actions.get("dry_run", True))
    reason = "；".join(decision.reasons) or "温度持续超限"
    wait_seconds = _critical_wait_seconds(config)
    delivered = notify_mod.notify_blocking(
        "TRIP",
        f"持续高温，终止进程。{reason}",
        config,
        timeout=wait_seconds,
    )
    if not delivered:
        _local_critical_fallback(f"终止进程告警未送达：{reason}")
        notify_mod.notify(
            "WARN",
            f"关键告警未在 {wait_seconds:.0f}s 内确认送达；仍按温度安全策略继续",
            config,
        )

    if not names:
        notify_mod.notify("WARN", "没有配置 actions.terminate_processes，跳过终止", config)
        return True
    if psutil is None:
        notify_mod.notify("WARN", "未安装 psutil，无法终止进程", config)
        return False

    protect_keywords = actions.get("protect_keywords") or []
    if isinstance(protect_keywords, str):
        protect_keywords = [protect_keywords]
    matches = _find_processes(names, protect_keywords)
    if not matches:
        notify_mod.notify(
            "INFO", "没有找到要终止的进程：" + "、".join(names), config
        )
        return True

    if dry_run:
        for name, pid in matches:
            notify_mod.notify("INFO", f"演习：假装终止了 {name}({pid})", config)
        return True

    all_ok = True
    for name, pid in matches:
        tag = f"{name}({pid})"
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except psutil.TimeoutExpired:
                proc.kill()
            notify_mod.notify("INFO", f"已终止 {tag}", config)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            all_ok = False
            notify_mod.notify("WARN", f"终止 {tag} 失败：{exc}", config)
        except Exception as exc:
            all_ok = False
            notify_mod.notify("WARN", f"终止 {tag} 失败：{exc}", config)
    return all_ok


def _schedule_shutdown(delay_seconds: int) -> Tuple[bool, str]:
    """Windows 关机；返回 (是否成功, 错误信息)。"""
    if os.name != "nt":
        return False, "自动关机目前只支持 Windows"
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            ["shutdown", "/s", "/t", str(delay_seconds)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
            check=False,
        )
        if result.returncode == 0:
            return True, ""
        detail = (result.stderr or result.stdout or f"退出码 {result.returncode}").strip()
        return False, detail
    except Exception as exc:
        return False, str(exc)


def _handle_shutdown(decision: fuse_mod.Decision, config: dict) -> bool:
    """处理“关机”状态。演习模式绝不真关机。返回是否已成功处理。"""
    actions = config.get("actions") or {}
    dry_run = bool(actions.get("dry_run", True))
    try:
        delay = max(0, int(actions.get("shutdown_delay_seconds", 60)))
    except Exception:
        delay = 60

    reason = "；".join(decision.reasons) or "温度达到关机线"
    wait_seconds = _critical_wait_seconds(config)
    delivered = notify_mod.notify_blocking(
        "TRIP",
        f"危险高温，需要关机。{reason}",
        config,
        timeout=wait_seconds,
    )
    if not delivered:
        _local_critical_fallback(f"关机告警未送达：{reason}")
        notify_mod.notify(
            "WARN",
            f"关键关机告警未在 {wait_seconds:.0f}s 内确认送达；仍执行温度安全策略",
            config,
        )

    if dry_run:
        notify_mod.notify(
            "WARN", f"演习：本该在 {delay}s 后关机，已跳过（不会执行 shutdown）", config
        )
        return True

    ok, detail = _schedule_shutdown(delay)
    if ok:
        notify_mod.notify(
            "TRIP", f"已计划 {delay}s 后关机；取消请运行：shutdown /a", config
        )
        return True
    notify_mod.notify("WARN", f"自动关机失败：{detail}", config)
    return False


def _handle_state(
    decision: fuse_mod.Decision,
    prev_state: Optional[str],
    config: dict,
    journal: Optional[action_journal_mod.ActionJournal] = None,
    retry_seconds: float = 60.0,
) -> None:
    """状态变化时告警；危险动作失败/被取消后按间隔重试。"""
    state = decision.state
    reason = "；".join(decision.reasons) or "温度状态变化"

    if state == fuse_mod.SAFE:
        if prev_state in (fuse_mod.WARNING, fuse_mod.TERMINATE, fuse_mod.SHUTDOWN):
            hottest = _fmt(decision.hottest) or "?"
            notify_mod.notify("INFO", f"温度恢复正常：最热 {hottest}°C", config)
        if journal is not None:
            # 状态回到安全：清掉旧的 failed/scheduled 记录。
            # 若 shutdown 已被用户取消，下一次高温可以重新发起动作。
            journal.clear()
        return

    if state == fuse_mod.WARNING:
        if prev_state != fuse_mod.WARNING:
            notify_mod.notify("WARN", f"温度警告：{reason}", config)
        return

    if state in (fuse_mod.TERMINATE, fuse_mod.SHUTDOWN):
        if journal is not None:
            if not journal.should_attempt(state, retry_seconds):
                return
            journal.begin(state, reason)
            try:
                ok = (
                    _handle_terminate(decision, config)
                    if state == fuse_mod.TERMINATE
                    else _handle_shutdown(decision, config)
                )
            except Exception as exc:
                journal.finish(state, "failed", str(exc))
                notify_mod.notify("WARN", f"{state} 动作异常：{exc}", config)
                return
            if ok:
                status = "scheduled" if state == fuse_mod.SHUTDOWN else "done"
                journal.finish(state, status)
            else:
                journal.finish(state, "failed", "动作返回失败，见告警/日志")
            return
        # 没有 journal 的兼容路径：只在状态变化时执行一次。
        if prev_state != state:
            if state == fuse_mod.TERMINATE:
                _handle_terminate(decision, config)
            else:
                _handle_shutdown(decision, config)


# ---------------------------------------------------------------- 主循环

def _duration_text(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.0f} 分钟"
    return f"{seconds:.0f} 秒"


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, value: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def _cold_boot() -> bool:
    """同一 Windows 启动周期内只保护第一次启动，避免重启绕过安全动作。"""
    state_path = ROOT / "logs" / "boot_state.json"
    try:
        current = float(psutil.boot_time()) if psutil is not None else time.time()
    except Exception:
        current = time.time()
    cold = True
    try:
        if state_path.exists():
            previous = float(json.loads(state_path.read_text(encoding="utf-8"))["boot_time"])
            cold = abs(previous - current) > 2.0
    except Exception:
        cold = True
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"boot_time": current, "checked_at": time.time()}),
            encoding="utf-8",
        )
        tmp.replace(state_path)
    except Exception:
        pass
    return cold


def run(config: dict, once: bool = False, dry_run: Optional[bool] = None) -> int:
    sample_cfg = config.get("sample") or {}
    interval = max(1.0, float(sample_cfg.get("interval_seconds", 5)))
    log_path = Path(sample_cfg.get("log_file") or "logs/temps.csv")
    if not log_path.is_absolute():
        log_path = ROOT / log_path
    max_log_bytes = int(sample_cfg.get("max_log_bytes", 20 * 1024 * 1024))

    cold_boot = _cold_boot()
    fuse = fuse_mod.Fuse(
        config.get("thresholds"),
        safety=config.get("safety"),
        cold_boot=cold_boot,
    )
    fuse_state_path = ROOT / "logs" / "fuse_state.json"
    if not cold_boot:
        fuse.restore_state(_load_json(fuse_state_path))
    journal = action_journal_mod.ActionJournal(ROOT / "logs" / "action_state.json")
    if cold_boot:
        journal.clear()
    try:
        action_retry_seconds = max(
            5.0, float((config.get("actions") or {}).get("retry_seconds", 60))
        )
    except (TypeError, ValueError):
        action_retry_seconds = 60.0
    sensors_cfg = config.get("sensors") or {}
    safety_cfg = config.get("safety") or {}
    sensor_keys = tuple(
        key for key in ("cpu", "gpu") if bool(sensors_cfg.get(key, True))
    )
    try:
        sensor_stale_seconds = max(1.0, float(safety_cfg.get("sensor_stale_seconds", 20)))
    except (TypeError, ValueError):
        sensor_stale_seconds = 20.0
    try:
        sensor_loss_seconds = max(0.0, float(safety_cfg.get("sensor_loss_seconds", 300)))
    except (TypeError, ValueError):
        sensor_loss_seconds = 300.0
    sensor_loss_action = str(safety_cfg.get("sensor_loss_action") or "warn").lower()
    sensor_lost_since: Optional[float] = None
    sensor_loss_warned = False
    sensor_partial_warned = False
    monitor_cfg = config.get("monitor") or {}
    heartbeat_url = str(monitor_cfg.get("heartbeat_url") or "").strip()
    heartbeat_token = str(monitor_cfg.get("heartbeat_token") or "")
    try:
        heartbeat_interval = max(
            10.0, float(monitor_cfg.get("heartbeat_interval_seconds", 60))
        )
    except (TypeError, ValueError):
        heartbeat_interval = 60.0
    last_heartbeat = 0.0

    actions = dict(config.get("actions") or {})
    if dry_run is not None:
        actions["dry_run"] = dry_run
    config = dict(config)
    config["actions"] = actions
    dry = bool(actions.get("dry_run", True))
    notify_cfg = config.get("notify") or {}
    astrbot_cfg = notify_cfg.get("astrbot") or {}
    email_cfg = notify_cfg.get("email") or {}
    wechat_webhook = str(
        (notify_cfg.get("wechat") or {}).get("webhook")
        or (notify_cfg.get("phone") or {}).get("webhook")
        or ""
    ).strip()

    mode = str(notify_cfg.get("mode") or "direct").strip().lower()
    alertd_cfg = notify_cfg.get("alertd") or {}
    channels = []
    if mode == "alertd" and alertd_cfg.get("enabled"):
        channels.append("alertd")
    else:
        if astrbot_cfg.get("enabled") and astrbot_cfg.get("api_key") and astrbot_cfg.get("umos"):
            channels.append("AstrBot")
        if wechat_webhook:
            channels.append("企业微信")
        if email_cfg.get("enabled") and email_cfg.get("smtp_host") and email_cfg.get("to_addrs"):
            channels.append("邮件")
    channel_text = "、".join(channels) or "仅屏幕"

    notify_mod.notify(
        "INFO",
        f"temguard 启动：每 {interval:g}s 检查一次，"
        f"警告线 {fuse.warning_c:.0f}°C，"
        f"连续 {_duration_text(fuse.terminate_seconds)} ≥ {fuse.terminate_c:.0f}°C 终止进程，"
        f"连续 {fuse.shutdown_samples} 次 ≥ {fuse.shutdown_c:.0f}°C 关机；"
        f"启动保护 {fuse.startup_grace_seconds:.0f}s（仅冷启动）；"
        f"推送：{channel_text}；"
        f"{'演习模式（不真动手）' if dry else '真实模式'}",
        config,
    )

    try:
        fh, writer = _open_log(log_path, max_log_bytes)
    except Exception as exc:
        notify_mod.notify("WARN", f"无法打开日志文件 {log_path}：{exc}，已停止", config)
        return 1

    prev_state: Optional[str] = None
    try:
        while True:
            tick = time.monotonic()
            try:
                temps = sensors.read_temperatures(sensors_cfg)
                decision = fuse.feed(temps)
                health = sensors.sensor_health(
                    sensor_keys,
                    stale_seconds=sensor_stale_seconds,
                )
                all_stale = bool(sensor_keys) and all(
                    health[key]["stale"] for key in sensor_keys
                )
                stale_keys = [key for key in sensor_keys if health[key]["stale"]]
                if stale_keys and not all_stale and not sensor_partial_warned:
                    notify_mod.notify(
                        "WARN",
                        "部分温度源失效：" + "、".join(stale_keys) + "；仍用剩余传感器判断",
                        config,
                    )
                    sensor_partial_warned = True
                elif not stale_keys:
                    sensor_partial_warned = False
                if all_stale:
                    if sensor_lost_since is None:
                        sensor_lost_since = time.monotonic()
                    lost_for = time.monotonic() - sensor_lost_since
                    if (
                        sensor_loss_action == "shutdown"
                        and sensor_loss_seconds > 0
                        and lost_for >= sensor_loss_seconds
                    ):
                        decision = fuse_mod.Decision(
                            fuse_mod.SHUTDOWN,
                            None,
                            None,
                            [f"温度传感器全部失效 {lost_for:.0f}s，执行 fail-safe"],
                            armed=True,
                        )
                    elif not sensor_loss_warned:
                        notify_mod.notify(
                            "WARN",
                            f"温度传感器全部失效 {lost_for:.0f}s；"
                            f"将在 {sensor_loss_seconds:.0f}s 后执行 {sensor_loss_action}",
                            config,
                        )
                        sensor_loss_warned = True
                else:
                    sensor_lost_since = None
                    sensor_loss_warned = False

                _write_json(fuse_state_path, fuse.export_state())

                if heartbeat_url and tick - last_heartbeat >= heartbeat_interval:
                    heartbeat_mod.send_heartbeat(
                        heartbeat_url,
                        heartbeat_token,
                        {
                            "source": "temguard",
                            "state": decision.state,
                            "cpu": temps.get("cpu"),
                            "gpu": temps.get("gpu"),
                            "time": dt.datetime.now().isoformat(timespec="seconds"),
                        },
                    )
                    last_heartbeat = tick

                writer.writerow([
                    dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    _fmt(temps.get("cpu")),
                    _fmt(temps.get("gpu")),
                    _fmt(decision.hottest),
                    decision.state,
                    "；".join(decision.reasons),
                ])
                fh.flush()

                _handle_state(
                    decision,
                    prev_state,
                    config,
                    journal,
                    action_retry_seconds,
                )
                prev_state = decision.state

                if once:
                    reason = "；".join(decision.reasons) or "-"
                    print(
                        f"CPU: {_fmt(temps.get('cpu')) or '读不到'}   "
                        f"GPU: {_fmt(temps.get('gpu')) or '读不到'}   "
                        f"状态: {decision.label}   {reason}",
                        flush=True,
                    )
                    return 0

            except Exception as exc:
                notify_mod.notify(
                    "WARN",
                    f"本轮出错：{type(exc).__name__}: {exc}，继续运行",
                    config,
                )
                if once:
                    return 1

            time.sleep(max(0.0, interval - (time.monotonic() - tick)))

    except KeyboardInterrupt:
        notify_mod.notify("INFO", "收到 Ctrl+C，temguard 已停止", config)
        return 0
    finally:
        try:
            fh.close()
        except Exception:
            pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="temguard —— 温度看门狗")
    parser.add_argument("--config", default=str(_default_config_path()), help="配置文件路径")
    parser.add_argument("--once", action="store_true", help="只检查一次就退出")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="强制演习模式（覆盖 config 里的 actions.dry_run）",
    )
    parser.add_argument(
        "--test-notify",
        "--test-wechat",
        dest="test_notify",
        action="store_true",
        help="给所有已配置的告警通道发送一条测试消息后退出",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config))
    except Exception as exc:
        print(f"读取配置失败：{exc}")
        return 1

    if args.test_notify:
        ok = notify_mod.send_test(config)
        print(
            "测试消息发送成功（至少一个通道）"
            if ok
            else "测试消息发送失败：检查 AstrBot/微信/邮件配置和网络"
        )
        return 0 if ok else 1

    lock = None
    if not args.once:
        try:
            lock = InstanceLock("temguard", ROOT / "logs").acquire()
        except AlreadyRunning as exc:
            print(f"temguard 未启动：{exc}")
            return 0

    try:
        return run(config, once=args.once, dry_run=True if args.dry_run else None)
    except Exception as exc:
        print(f"temguard 启动失败：{type(exc).__name__}: {exc}")
        return 1
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
