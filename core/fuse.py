"""脑：四态熔断判断。

每次收到最新的 CPU/GPU 温度，回答四种状态之一：

    safe       安全：温度正常，什么都不用做
    warning    警告：温度偏高，但还没到拉闸条件
    terminate  终止进程：连续长时间 ≥ terminate_c（默认 93°C，20 分钟）
    shutdown   关机：连续 shutdown_samples 次（默认 3 次）≥ shutdown_c（默认 95°C）

关键点：
- 偶尔冲一下不算，规则只认“连续”；
- 温度掉回正常（低于 reset_c）所有计数清零；
- 中间只要掉到阈值以下，对应计时/计数就重来。

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

    @property
    def label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)


class Fuse:
    """维护温度计时/计数，输出四态。"""

    def __init__(self, thresholds: Optional[dict] = None):
        cfg = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
        self.warning_c = float(cfg["warning_c"])
        self.terminate_c = float(cfg["terminate_c"])
        self.shutdown_c = float(cfg["shutdown_c"])
        self.reset_c = float(cfg["reset_c"])
        self.terminate_seconds = max(0.0, float(cfg["terminate_seconds"]))
        self.shutdown_samples = max(1, int(cfg["shutdown_samples"]))

        self._terminate_since: Optional[float] = None
        self._shutdown_streak = 0

    def reset(self) -> None:
        """清空所有计时/计数。"""
        self._terminate_since = None
        self._shutdown_streak = 0

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
            self.reset()
            return Decision(WARNING, None, None, ["读不到 CPU/GPU 温度"])

        sensor, hottest = max(values.items(), key=lambda item: item[1])

        # 回到正常温度：全部清零。
        if hottest < self.reset_c:
            self.reset()
            return Decision(SAFE, hottest, sensor)

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

        if self._shutdown_streak >= self.shutdown_samples:
            return Decision(
                SHUTDOWN, hottest, sensor,
                [
                    f"{label} {hottest:.1f}°C 连续 {self._shutdown_streak} 次 "
                    f"≥ {self.shutdown_c:.0f}°C"
                ],
                held, self._shutdown_streak,
            )

        if self._terminate_since is not None and held >= self.terminate_seconds:
            return Decision(
                TERMINATE, hottest, sensor,
                [
                    f"{label} {hottest:.1f}°C 已连续 {held:.0f}s "
                    f"≥ {self.terminate_c:.0f}°C"
                ],
                held, self._shutdown_streak,
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
            return Decision(
                WARNING, hottest, sensor, [reason], held, self._shutdown_streak
            )

        return Decision(SAFE, hottest, sensor, [], held, self._shutdown_streak)


# ---------------------------------------------------------------- 自检

if __name__ == "__main__":
    # 假数据：前段演示瞬时峰值不会升级；后段演示连续超温升级到关机。
    steps = [
        (0, 70.0, 60.0),      # 安全
        (10, 91.0, 60.0),     # 警告
        (30, 96.0, 60.0),     # 警告：关机计数 1/3
        (35, 80.0, 60.0),     # 安全：瞬时峰值被清零
        (40, 94.0, 60.0),     # 警告：开始累计 93°C 时长
        (1239, 94.0, 60.0),   # 警告：已持续 1199s
        (1240, 94.0, 60.0),   # 终止进程：满 1200s
        (1245, 96.0, 60.0),   # 终止进程：关机计数 1/3
        (1246, 96.0, 60.0),   # 终止进程：关机计数 2/3
        (1247, 96.0, 60.0),   # 关机：3/3
        (1300, 80.0, 60.0),   # 安全：温度降回正常，清零
    ]

    fuse = Fuse()
    print("四态熔断测试（假数据，不会真关机）")
    print("-" * 92)
    print(f"{'时刻':>7}  {'CPU':>6}  {'GPU':>6}  {'状态':<6} 说明")
    print("-" * 92)
    for timestamp, cpu, gpu in steps:
        decision = fuse.feed({"cpu": cpu, "gpu": gpu}, now=timestamp)
        reason = "；".join(decision.reasons) or "-"
        print(
            f"{timestamp:>5}s  {cpu:>5.1f}°C  {gpu:>5.1f}°C  "
            f"{decision.label:<6} {reason}"
        )
    print("-" * 92)
    print("测试结束：注意瞬时 96°C 只到警告，连续规则满足后才升级。")
