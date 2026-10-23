"""安全故障演练：不加热硬件，只对 fuse 状态机做故障注入。

运行：
    python tools/fault_drill.py

这不是硬件烤机，不会真的关机/杀进程；它验证：
- 冷启动假高温只警告；
- 同一启动周期重启后不再有保护窗口；
- 传感器全部缺失是 warning，不是 safe。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.fuse import Fuse, SAFE, SHUTDOWN, WARNING


THRESHOLDS = {
    "warning_c": 90,
    "terminate_c": 93,
    "shutdown_c": 95,
    "reset_c": 88,
    "terminate_seconds": 1,
    "shutdown_samples": 3,
}


def run() -> int:
    failures = []

    cold = Fuse(
        THRESHOLDS,
        {"startup_grace_seconds": 180, "require_cool_baseline": True},
        cold_boot=True,
    )
    cold_states = [cold.feed({"cpu": 120}, now=float(i)).state for i in range(5)]
    print("cold boot 120C:", cold_states)
    if SHUTDOWN in cold_states:
        failures.append("冷启动假高温触发了 shutdown")

    hot_restart = Fuse(
        THRESHOLDS,
        {"startup_grace_seconds": 180, "require_cool_baseline": True},
        cold_boot=False,
    )
    restart_states = [hot_restart.feed({"cpu": 120}, now=float(i)).state for i in range(3)]
    print("same-boot restart 120C:", restart_states)
    if restart_states[-1] != SHUTDOWN:
        failures.append("同一启动周期重启后仍被启动保护挡住")

    missing = Fuse(THRESHOLDS, cold_boot=False)
    missing_state = missing.feed({"cpu": None, "gpu": None}).state
    print("all sensors missing:", missing_state)
    if missing_state not in (WARNING, SHUTDOWN):
        failures.append("传感器缺失没有进入 warning")

    if failures:
        print("FAIL:")
        for item in failures:
            print(" -", item)
        return 1
    print("PASS: fuse 故障注入全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
