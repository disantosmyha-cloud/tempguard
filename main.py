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
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from core import fuse as fuse_mod
from core import notify as notify_mod
from core import sensors

try:
    import psutil
except Exception:
    psutil = None

ROOT = Path(__file__).resolve().parent
CSV_HEADER = ["time", "cpu", "gpu", "hottest", "state", "reason"]


# ---------------------------------------------------------------- 配置 / 日志

def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _default_config_path() -> Path:
    """本机有 config.local.yaml 就优先用它；公开仓库只有 config.yaml。"""
    local = ROOT / "config.local.yaml"
    return local if local.exists() else ROOT / "config.yaml"


def _open_log(path: Path):
    """追加打开 CSV；新文件写表头，旧表头不匹配则改名备份。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = not path.exists() or path.stat().st_size == 0

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


def _find_processes(names: List[str]) -> List[Tuple[str, int]]:
    targets = {
        str(name).strip().lower()
        for name in (names or [])
        if str(name).strip()
    }
    if not targets or psutil is None:
        return []

    protected = _protected_pids()
    matches: List[Tuple[str, int]] = []
    try:
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                info = proc.info or {}
                pid = info.get("pid")
                name = str(info.get("name") or "")
                if pid in protected or not name:
                    continue
                if name.lower() in targets:
                    matches.append((name, int(pid)))
            except Exception:
                continue
    except Exception:
        pass
    return matches


def _handle_terminate(decision: fuse_mod.Decision, config: dict) -> None:
    """处理“终止进程”状态。"""
    actions = config.get("actions") or {}
    names = actions.get("terminate_processes") or []
    if isinstance(names, str):
        names = [names]
    dry_run = bool(actions.get("dry_run", True))
    reason = "；".join(decision.reasons) or "温度持续超限"

    notify_mod.notify("TRIP", f"持续高温，终止进程。{reason}", config)

    if not names:
        notify_mod.notify("WARN", "没有配置 actions.terminate_processes，跳过终止", config)
        return
    if psutil is None:
        notify_mod.notify("WARN", "未安装 psutil，无法终止进程", config)
        return

    matches = _find_processes(names)
    if not matches:
        notify_mod.notify(
            "INFO", "没有找到要终止的进程：" + "、".join(names), config
        )
        return

    if dry_run:
        for name, pid in matches:
            notify_mod.notify("INFO", f"演习：假装终止了 {name}({pid})", config)
        return

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
            notify_mod.notify("WARN", f"终止 {tag} 失败：{exc}", config)
        except Exception as exc:
            notify_mod.notify("WARN", f"终止 {tag} 失败：{exc}", config)


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


def _handle_shutdown(decision: fuse_mod.Decision, config: dict) -> None:
    """处理“关机”状态。演习模式绝不真关机。"""
    actions = config.get("actions") or {}
    dry_run = bool(actions.get("dry_run", True))
    try:
        delay = max(0, int(actions.get("shutdown_delay_seconds", 60)))
    except Exception:
        delay = 60

    reason = "；".join(decision.reasons) or "温度达到关机线"
    notify_mod.notify("TRIP", f"危险高温，需要关机。{reason}", config)

    if dry_run:
        notify_mod.notify(
            "WARN", f"演习：本该在 {delay}s 后关机，已跳过（不会执行 shutdown）", config
        )
        return

    ok, detail = _schedule_shutdown(delay)
    if ok:
        notify_mod.notify(
            "TRIP", f"已计划 {delay}s 后关机；取消请运行：shutdown /a", config
        )
    else:
        notify_mod.notify("WARN", f"自动关机失败：{detail}", config)


def _handle_state(
    decision: fuse_mod.Decision,
    prev_state: Optional[str],
    config: dict,
) -> None:
    """只在状态变化时发告警，避免每 5 秒刷屏。"""
    state = decision.state

    if state == fuse_mod.SAFE:
        if prev_state in (fuse_mod.WARNING, fuse_mod.TERMINATE, fuse_mod.SHUTDOWN):
            hottest = _fmt(decision.hottest) or "?"
            notify_mod.notify("INFO", f"温度恢复正常：最热 {hottest}°C", config)
        return

    if state == fuse_mod.WARNING:
        if prev_state != fuse_mod.WARNING:
            notify_mod.notify(
                "WARN", "温度警告：" + ("；".join(decision.reasons) or "温度偏高"), config
            )
        return

    if state == fuse_mod.TERMINATE:
        if prev_state != fuse_mod.TERMINATE:
            _handle_terminate(decision, config)
        return

    if state == fuse_mod.SHUTDOWN:
        if prev_state != fuse_mod.SHUTDOWN:
            _handle_shutdown(decision, config)


# ---------------------------------------------------------------- 主循环

def _duration_text(seconds: float) -> str:
    if seconds >= 60:
        return f"{seconds / 60:.0f} 分钟"
    return f"{seconds:.0f} 秒"


def run(config: dict, once: bool = False, dry_run: Optional[bool] = None) -> int:
    sample_cfg = config.get("sample") or {}
    interval = max(1.0, float(sample_cfg.get("interval_seconds", 5)))
    log_path = Path(sample_cfg.get("log_file") or "logs/temps.csv")
    if not log_path.is_absolute():
        log_path = ROOT / log_path

    fuse = fuse_mod.Fuse(
        config.get("thresholds"),
        safety=config.get("safety"),
    )
    sensors_cfg = config.get("sensors") or {}

    actions = dict(config.get("actions") or {})
    if dry_run is not None:
        actions["dry_run"] = dry_run
    config = dict(config)
    config["actions"] = actions
    dry = bool(actions.get("dry_run", True))

    notify_mod.notify(
        "INFO",
        f"temguard 启动：每 {interval:g}s 检查一次，"
        f"警告线 {fuse.warning_c:.0f}°C，"
        f"连续 {_duration_text(fuse.terminate_seconds)} ≥ {fuse.terminate_c:.0f}°C 终止进程，"
        f"连续 {fuse.shutdown_samples} 次 ≥ {fuse.shutdown_c:.0f}°C 关机；"
        f"启动保护 {fuse.startup_grace_seconds:.0f}s；"
        f"{'演习模式（不真动手）' if dry else '真实模式'}",
        config,
    )

    try:
        fh, writer = _open_log(log_path)
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

                writer.writerow([
                    dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    _fmt(temps.get("cpu")),
                    _fmt(temps.get("gpu")),
                    _fmt(decision.hottest),
                    decision.state,
                    "；".join(decision.reasons),
                ])
                fh.flush()

                _handle_state(decision, prev_state, config)
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
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config))
    except Exception as exc:
        print(f"读取配置失败：{exc}")
        return 1

    try:
        return run(config, once=args.once, dry_run=True if args.dry_run else None)
    except Exception as exc:
        print(f"temguard 启动失败：{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
