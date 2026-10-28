"""演练死手开关：按回车触发一次 TRIP 告警；不启动/停止任何服务。

用法：
    python tools/deadman_sim.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import main as temguard_main
from core import notify
from core.deadman import MockDeadManSwitch


def main() -> int:
    config = temguard_main.load_config(ROOT / "config.local.yaml")
    switch = MockDeadManSwitch()
    print("死手开关模拟：按回车触发 TRIP，Ctrl+C 退出。")
    try:
        input("按回车...")
    except (EOFError, KeyboardInterrupt):
        return 0
    switch.trigger("terminal enter key")
    event = switch.poll()
    if event is None:
        print("没有事件")
        return 1
    ok = notify.notify_blocking(
        "TRIP",
        f"死手开关演练触发：{event.reason}",
        config,
        timeout=12,
        idempotency_key=f"deadman:{int(event.at)}",
    )
    print(f"delivered={ok} source={event.source} reason={event.reason}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
