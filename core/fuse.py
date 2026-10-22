"""脑：四态熔断判断。

每次收到最新的 CPU/GPU 温度，回答四种状态之一：

    safe       安全：温度正常，什么都不用做
    warning    警告：温度偏高，但还没到拉闸条件
    terminate  终止进程：连续长时间 ≥ terminate_c（默认 93°C，20 分钟）
    shutdown   关机：连续 shutdown_samples 次（默认 3 次）≥ shutdown_c（默认 95°C）

关键点：
- 偶尔冲一下不算，规则只认“连续”；
- 温度掉回正常（低于 reset_c）所有计数清零；
- 中间只要掉到阈值以下，对应计时/计数就重来；
- 开机/刚启动有保护期：默认前 3 分钟、且还没读到过一次正常温度时，
  只警告，不终止进程、不关机。避免 LHM/驱动刚启动时的假高温把电脑关掉。

模块末尾有假数据测试，直接 `python core\\fuse.py` 就能看到状态升级全过程。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 四态
SAFE = "safe"
WARNING = "warning"
TERMINATE = "terminate"
SHUTDOWN = "shutdown"

STATE_LABELS = {
    SAFE: "安全",
    WARNING: "警告",
    TERMINATE: "终止进程",
    SHUTDOWN: "关机",
}
_SENSOR_LABELS = {"cpu": "CPU", "gpu": "GPU"}

# 默认阈值，和 config.yaml 里的初始值保持一致。
DEFAULT_THRESHOLDS = {
    "warning_c": 90.0,
    "terminate_c": 93.0,
    "shutdown_c": 95.0,
    "reset_c": 88.0,
    "terminate_seconds": 1200.0,  # 20 分钟
    "shutdown_samples": 3,
}

DEFAULT_SAFETY = {
    "startup_grace_seconds": 180.0,   # 启动后 3 分钟内只警告不动手
    "require_cool_baseline": True,    # 必须先读到一次 < warning_c 的正常温度
}


def _as_number(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


@dataclass
class Decision:
    """一次判断的结果。"""

    state: str
    hottest: Optional[float] = None            # 最热的温度
    sensor: Optional[str] = None               # "cpu" / "gpu"
    reasons: List[str] = field(default_factory=list)
    terminate_held: float = 0.0                # 已连续 ≥ terminate_c 的秒数
    shutdown_streak: int = 0                   # 已连续 ≥ shutdown_c 的次数
    armed: bool = False                        # 是否已过启动保护期、允许动作
    startup_remaining: float = 0.0             # 启动保护期剩余秒数

    @property
    def label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)


class Fuse:
    """维护温度计时/计数，输出四态。"""

    def __init__(
        self,
        thresholds: Optional[dict] = None,
        safety: Optional[dict] = None,
    ):
        cfg = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.warning_c = float(cfg["warning_c"])
        self.terminate_c = float(cfg["terminate_c"])
        self.shutdown_c = float(cfg["shutdown_c"])
        self.reset_c = float(cfg["reset_c"])
        self.terminate_seconds = max(0.0, float(cfg["terminate_seconds"]))
        self.shutdown_samples = max(1, int(cfg["shutdown_samples"]))

        safe = {**DEFAULT_SAFETY, **(safety or {})}
        self.startup_grace_seconds = max(0.0, float(safe["startup_grace_seconds"]))
        self.require_cool_baseline = bool(safe["require_cool_baseline"])

        self._terminate_since: Optional[float] = None
        self._shutdown_streak = 0
        self._started_at: Optional[float] = None
        self._cool_seen = False
        self._armed = False

    def reset(self) -> None:
        """清空计时/计数（不清启动保护状态）。"""
        self._terminate_since = None
        self._shutdown_streak = 0

    def _update_armed(self, now: float, hottest: Optional[float]) -> float:
        """更新启动保护状态，返回保护期剩余秒数。"""
        if self._started_at is None:
            self._started_at = now
        if hottest is not None and hottest < self.warning_c:
            self._cool_seen = True

        elapsed = now - self._started_at
        remaining = max(0.0, self.startup_grace_seconds - elapsed)
        was_armed = self._armed
        self._armed = (
            remaining <= 0.0
            and (self._cool_seen or not self.require_cool_baseline)
        )
        # 保护期结束时丢掉保护期内累计的高温次数/时长，
        # 避免开机那几分钟的假高温直接触发动作。
        if self._armed and not was_armed:
            self.reset()
        return remaining

    def _protection_note(self, remaining: float) -> str:
        if remaining > 0:
            return f"启动保护期剩余 {remaining:.0f}s，暂不动作"
        return (
            f"还没读到低于 {self.warning_c:.0f}°C 的正常温度基线，"
            "暂不动作"
        )

    def feed(
        self,
        temps: Dict[str, Optional[float]],
        now: Optional[float] = None,
    ) -> Decision:
        """喂一次温度（°C），返回本轮四态判断。"""
        now = time.monotonic() if now is None else now

        values: Dict[str, float] = {}
        for key in ("cpu", "gpu"):
            number = _as_number((temps or {}).get(key))
            if number is not None:
                values[key] = number

        # 一个都读不到：按警告处理，但不要基于旧数据继续计时。
        if not values:
            remaining = self._update_armed(now, None)
            self.reset()
            return Decision(
                WARNING, None, None, ["读不到 CPU/GPU 温度"],
                armed=self._armed, startup_remaining=remaining,
            )

        sensor, hottest = max(values.items(), key=lambda item: item[1])
        remaining = self._update_armed(now, hottest)

        # 回到正常温度：全部清零。
        if hottest < self.reset_c:
            self.reset()
            return Decision(
                SAFE, hottest, sensor, [],
                armed=self._armed, startup_remaining=remaining,
            )

        # 关机是更高优先级：连续 N 次 ≥ shutdown_c。
        if hottest >= self.shutdown_c:
            self._shutdown_streak += 1
        else:
            self._shutdown_streak = 0

        # terminate 只认连续 ≥ terminate_c 的时长。
        if hottest >= self.terminate_c:
            if self._terminate_since is None:
                self._terminate_since = now
            held = now - self._terminate_since
        else:
            self._terminate_since = None
            held = 0.0

        label = _SENSOR_LABELS.get(sensor, sensor.upper())
        protection = None if self._armed else self._protection_note(remaining)

        if self._shutdown_streak >= self.shutdown_samples:
            reason = (
                f"{label} {hottest:.1f}°C 连续 {self._shutdown_streak} 次 "
                f"≥ {self.shutdown_c:.0f}°C"
            )
            if protection:
                return Decision(
                    WARNING, hottest, sensor, [f"{reason}；{protection}"],
                    held, self._shutdown_streak, False, remaining,
                )
            return Decision(
                SHUTDOWN, hottest, sensor, [reason],
                held, self._shutdown_streak, True, remaining,
            )

        if self._terminate_since is not None and held >= self.terminate_seconds:
            reason = (
                f"{label} {hottest:.1f}°C 已连续 {held:.0f}s "
                f"≥ {self.terminate_c:.0f}°C"
            )
            if protection:
                return Decision(
                    WARNING, hottest, sensor, [f"{reason}；{protection}"],
                    held, self._shutdown_streak, False, remaining,
                )
            return Decision(
                TERMINATE, hottest, sensor, [reason],
                held, self._shutdown_streak, True, remaining,
            )

        if hottest >= self.warning_c:
            if self._shutdown_streak:
                reason = (
                    f"{label} {hottest:.1f}°C 已连续 "
                    f"{self._shutdown_streak}/{self.shutdown_samples} 次 "
                    f"≥ {self.shutdown_c:.0f}°C"
                )
            elif self._terminate_since is not None:
                reason = (
                    f"{label} {hottest:.1f}°C 已持续 {held:.0f}s "
                    f"≥ {self.terminate_c:.0f}°C，"
                    f"满 {self.terminate_seconds:.0f}s 将终止进程"
                )
            else:
                reason = f"{label} {hottest:.1f}°C ≥ 警告线 {self.warning_c:.0f}°C"
            if protection:
                reason = f"{reason}；{protection}"
            return Decision(
                WARNING, hottest, sensor, [reason],
                held, self._shutdown_streak, self._armed, remaining,
            )

        return Decision(
            SAFE, hottest, sensor, [],
            held, self._shutdown_streak, self._armed, remaining,
        )


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":
    # 假数据：
    # 1) 开机假高温：连续 3 次 120°C，但启动保护期内只警告；
    # 2) 读到一次正常温度后，才允许进入后续的终止/关机规则。
    steps = [
        (0, 120.0, 60.0),     # 警告：启动保护期，关机计数 1/3
        (5, 120.0, 60.0),     # 警告：启动保护期，2/3
        (10, 120.0, 60.0),    # 警告：已连续 3 次，但保护期内不关机
        (15, 70.0, 60.0),     # 安全：读到正常温度，建立基线
        (40, 94.0, 60.0),     # 警告：保护期结束，开始累计 93°C 时长
        (1239, 94.0, 60.0),   # 警告：已持续 1199s
        (1240, 94.0, 60.0),   # 终止进程：满 1200s
        (1245, 96.0, 60.0),   # 终止进程：关机计数 1/3
        (1246, 96.0, 60.0),   # 终止进程：关机计数 2/3
        (1247, 96.0, 60.0),   # 关机：3/3
        (1300, 80.0, 60.0),   # 安全：温度降回正常，清零
    ]

    fuse = Fuse(safety={"startup_grace_seconds": 30, "require_cool_baseline": True})
    print("四态熔断测试（假数据，不会真关机）")
    print("-" * 100)
    print(f"{'时刻':>7}  {'CPU':>6}  {'GPU':>6}  {'状态':<6} 说明")
    print("-" * 100)
    for timestamp, cpu, gpu in steps:
        decision = fuse.feed({"cpu": cpu, "gpu": gpu}, now=timestamp)
        reason = "；".join(decision.reasons) or "-"
        print(
            f"{timestamp:>5}s  {cpu:>5.1f}°C  {gpu:>5.1f}°C  "
            f"{decision.label:<6} {reason}"
        )
    print("-" * 100)
    print("测试结束：启动阶段 120°C 也只警告；正常基线 + 连续规则满足后才升级。")
    print("（测试里把启动保护期缩短为 30 秒；正式 config.yaml 默认是 180 秒）")
