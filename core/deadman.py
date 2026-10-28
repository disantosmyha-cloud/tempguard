"""外部死手开关（dead-man switch）接口。

硬件还没选型时，主程序只依赖这个接口，不依赖任何板子/串口库：

    class DeadManSwitch:
        def poll(self) -> Optional[DeadManEvent]

以后 ESP32/Arduino/树莓派实现同一个 `poll()` 即可接上。当前提供：

- NullDeadManSwitch：没有硬件，永远不触发；
- MockDeadManSwitch：测试/演练用，手动 trigger 或超时触发。

真正的告警发送仍由 `core.notify` 或 alertd 负责，开关本身不发送消息。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class DeadManEvent:
    source: str
    reason: str
    at: float


class DeadManSwitch(ABC):
    """硬件抽象；实现者只需要给出 poll()。"""

    @abstractmethod
    def poll(self) -> Optional[DeadManEvent]:
        raise NotImplementedError

    def health(self) -> dict:
        return {"kind": type(self).__name__, "enabled": True}


class NullDeadManSwitch(DeadManSwitch):
    """未接硬件时的空实现。"""

    def poll(self) -> Optional[DeadManEvent]:
        return None

    def health(self) -> dict:
        return {"kind": "null", "enabled": False}


class MockDeadManSwitch(DeadManSwitch):
    """演练用：手动 trigger，或超过 timeout_seconds 未 confirm。

    timeout_seconds=0 表示只接受手动 trigger，不做超时检测。
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self._clock = clock
        self._last_confirm = clock()
        self._manual: Optional[DeadManEvent] = None
        self._fired = False

    def confirm(self) -> None:
        self._last_confirm = self._clock()
        self._fired = False

    def trigger(self, reason: str = "mock dead-man switch triggered") -> None:
        self._manual = DeadManEvent("mock", reason, self._clock())

    def poll(self) -> Optional[DeadManEvent]:
        if self._manual is not None:
            event = self._manual
            self._manual = None
            return event
        if self.timeout_seconds <= 0 or self._fired:
            return None
        if self._clock() - self._last_confirm >= self.timeout_seconds:
            self._fired = True
            return DeadManEvent(
                "mock",
                f"no confirmation for {self.timeout_seconds:.0f}s",
                self._clock(),
            )
        return None

    def health(self) -> dict:
        return {
            "kind": "mock",
            "enabled": True,
            "timeout_seconds": self.timeout_seconds,
            "last_confirm": self._last_confirm,
        }
