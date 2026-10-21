"""手①：读 CPU/GPU 温度、CPU 占用。

Windows 上最可靠的来源是 LibreHardwareMonitor：
开启它的 Remote Web Server 后，所有传感器会以 JSON 发布在
``http://127.0.0.1:8085/data.json``。
先用它；它没运行或没开 Web Server，再退回 psutil（Linux/macOS 可用）。

对外接口：
    read_cpu_temperature()  -> Optional[float]   # °C
    read_gpu_temperature()  -> Optional[float]   # °C
    read_cpu_usage()        -> Optional[float]   # 0~100
    read_temperatures(config) -> {"cpu": 62.5, "gpu": None}

设计原则只有一条：传感器是消耗品，读不到就返回 None。
这里的每个函数都会把异常吞掉，绝不把驱动、权限、HTTP 的问题扔给主循环 ——
这个程序要 24 小时挂机，稳定大于一切。
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from typing import Callable, Dict, Iterator, List, Optional, Tuple

try:
    import psutil
except Exception:  # psutil 缺失时只是少一个兜底来源
    psutil = None


SMI_TIMEOUT = 3.0              # nvidia-smi 超时，防止驱动卡死时拖住主循环
LHM_TIMEOUT = 2.0              # LHM Web Server 超时（本机 HTTP，正常是毫秒级）
LHM_CACHE_SECONDS = 0.5        # 同一轮采样里温度/占用共用一次 JSON
LHM_RETRY_SECONDS = 10.0       # LHM 没开时，10 秒内不重复请求
LHM_URL = os.environ.get(
    "TEMPGUARD_LHM_URL", "http://127.0.0.1:8085/data.json"
)

# 合理的温度范围（°C）。超出的读数多半是驱动/BIOS 返回的垃圾值，宁可当作读不到。
_MIN_C = -40.0
_MAX_C = 150.0

_CPU_KEYS = ("coretemp", "k10temp", "cpu_thermal", "acpitz")

# LHM 的传感器 Identifier 前缀。比 Name 稳定，不受界面语言/命名影响。
_CPU_ID_PREFIXES = ("/intelcpu/", "/amdcpu/", "/cpu/")
_GPU_ID_PREFIXES = (
    "/gpu-nvidia/",
    "/gpu-amd/",
    "/gpu-ati/",
    "/gpu-intel/",
    "/gpu/",
)

# LHM 一次采样结果：(Type, Name, Value, SensorId)
LhmReading = Tuple[str, str, float, str]

_lhm_lock = threading.Lock()
_lhm_cache: Optional[List[LhmReading]] = None
_lhm_cache_at = 0.0
_lhm_retry_at = 0.0

_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def _as_float(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _number_from_text(value) -> Optional[float]:
    """从 LHM 的 RawValue 里抠数字，例如 "86.9 °C" / "7.3 %"。"""
    if not isinstance(value, str):
        return _as_float(value)
    match = _NUMBER_RE.search(value)
    if not match:
        return None
    return _as_float(match.group(0).replace(",", "."))


def _plausible(value) -> bool:
    """判断一个读数是不是可信的摄氏度数字。"""
    number = _as_float(value)
    return number is not None and _MIN_C <= number <= _MAX_C


def _as_percent(value) -> Optional[float]:
    """判断一个读数是不是可信的 0~100 百分比。"""
    number = _as_float(value)
    if number is None or not 0.0 <= number <= 100.0:
        return None
    return number


def _first_reading(*readers: Callable[[], Optional[float]]) -> Optional[float]:
    """依次调用读取函数，返回第一个可信温度；全部失败就 None。"""
    for reader in readers:
        try:
            value = reader()
        except Exception:
            continue
        if _plausible(value):
            return float(value)
    return None


# ---------------------------------------------------------------- LHM JSON

def _walk_nodes(node) -> Iterator[dict]:
    """递归遍历 LHM 的 JSON 树。"""
    if not isinstance(node, dict):
        return
    yield node
    children = node.get("Children")
    if isinstance(children, list):
        for child in children:
            yield from _walk_nodes(child)


def _fetch_lhm_sensors() -> Optional[List[LhmReading]]:
    """请求 LHM 的 data.json，失败/超时返回 None。带 0.5s 缓存。"""
    global _lhm_cache, _lhm_cache_at, _lhm_retry_at

    now = time.monotonic()
    with _lhm_lock:
        if _lhm_cache is not None and now - _lhm_cache_at <= LHM_CACHE_SECONDS:
            return _lhm_cache
        if now < _lhm_retry_at:
            return None

    try:
        request = urllib.request.Request(
            LHM_URL, headers={"Cache-Control": "no-cache"}
        )
        with urllib.request.urlopen(request, timeout=LHM_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))

        readings: List[LhmReading] = []
        for node in _walk_nodes(payload):
            sensor_id = node.get("SensorId")
            sensor_type = node.get("Type")
            if not sensor_id or not sensor_type:
                continue
            if str(sensor_type).lower() not in ("temperature", "load"):
                continue
            value = _number_from_text(node.get("RawValue"))
            if value is None:
                continue
            readings.append(
                (
                    str(sensor_type),
                    str(node.get("Text") or ""),
                    value,
                    str(sensor_id),
                )
            )
    except Exception:
        # 没开 LHM、端口不对、JSON 坏了、被防火墙拦了……都按“没有这个来源”处理。
        with _lhm_lock:
            _lhm_retry_at = now + LHM_RETRY_SECONDS
        return None

    with _lhm_lock:
        _lhm_cache = readings
        _lhm_cache_at = time.monotonic()
        _lhm_retry_at = 0.0
    return readings


def _read_cpu_lhm() -> Optional[float]:
    """从 LHM 的 JSON 读 CPU 温度（取 CPU 传感器中的最高值）。"""
    readings = _fetch_lhm_sensors()
    if not readings:
        return None

    values = []
    for sensor_type, name, value, sensor_id in readings:
        if sensor_type.lower() != "temperature":
            continue
        if not sensor_id.lower().startswith(_CPU_ID_PREFIXES):
            continue
        # “Distance to TjMax”是距离上限的差值，不是当前温度。
        if "distance to tjmax" in name.lower():
            continue
        if _plausible(value):
            values.append(value)
    return max(values) if values else None


def _read_cpu_usage_lhm() -> Optional[float]:
    """从 LHM 的 JSON 读 CPU 总占用率（%）。"""
    readings = _fetch_lhm_sensors()
    if not readings:
        return None

    fallback = None
    for sensor_type, name, value, sensor_id in readings:
        if sensor_type.lower() != "load":
            continue
        if not sensor_id.lower().startswith(_CPU_ID_PREFIXES):
            continue
        percent = _as_percent(value)
        if percent is None:
            continue
        if name.strip().lower() == "cpu total":
            return percent
        if sensor_id.lower().endswith("/load/0"):
            fallback = percent
    return fallback


# ---------------------------------------------------------------- CPU 兜底

def _read_cpu_psutil() -> Optional[float]:
    """Linux/macOS 直接给核心温度；Windows 上通常没有这个接口。"""
    try:
        getter = getattr(psutil, "sensors_temperatures", None)
        if getter is None:
            return None
        groups = getter() or {}

        for key in _CPU_KEYS:
            values = [
                float(reading.current)
                for reading in (groups.get(key) or [])
                if _plausible(getattr(reading, "current", None))
            ]
            if values:
                return max(values)

        values = [
            float(reading.current)
            for readings in groups.values()
            for reading in (readings or [])
            if _plausible(getattr(reading, "current", None))
        ]
        return max(values) if values else None
    except Exception:
        return None


def _read_cpu_usage_psutil() -> Optional[float]:
    """LHM 不可用时的 CPU 占用兜底。"""
    try:
        if psutil is None:
            return None
        return _as_percent(psutil.cpu_percent(interval=0.1))
    except Exception:
        return None


# ---------------------------------------------------------------- GPU

def _find_nvidia_smi() -> Optional[str]:
    """找 nvidia-smi：先查 PATH，再查 NVIDIA 的常见安装位置。"""
    try:
        exe = shutil.which("nvidia-smi")
        if exe:
            return exe
    except Exception:
        pass

    names = ("nvidia-smi.exe", "nvidia-smi")
    dirs = []
    system_root = os.environ.get("SystemRoot") or os.environ.get("windir")
    if system_root:
        dirs.append(os.path.join(system_root, "System32"))
    for env_name in ("ProgramW6432", "ProgramFiles"):
        base = os.environ.get(env_name)
        if base:
            dirs.append(os.path.join(base, "NVIDIA Corporation", "NVSMI"))

    for directory in dirs:
        for name in names:
            candidate = os.path.join(directory, name)
            try:
                if os.path.isfile(candidate):
                    return candidate
            except OSError:
                continue
    return None


def _read_gpu_nvidia_smi() -> Optional[float]:
    """调用 NVIDIA 自带命令行工具读取 GPU 温度。"""
    try:
        exe = _find_nvidia_smi()
        if not exe:
            return None

        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        result = subprocess.run(
            [exe, "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SMI_TIMEOUT,
            creationflags=creation_flags,
            check=False,
        )
        if result.returncode != 0:
            return None

        values = []
        for line in (result.stdout or "").splitlines():
            try:
                value = float(line.strip())
            except (TypeError, ValueError):
                continue  # N/A、空行、错误信息一律跳过
            if _plausible(value):
                values.append(value)
        return max(values) if values else None
    except Exception:
        # 超时、驱动异常、权限不足、编码错误……全部按“读不到”处理。
        return None


def _read_gpu_lhm() -> Optional[float]:
    """从 LHM 的 JSON 读 GPU 温度（NVIDIA/AMD/Intel 都适用）。"""
    readings = _fetch_lhm_sensors()
    if not readings:
        return None

    gpu = [
        (name.lower(), value)
        for sensor_type, name, value, sensor_id in readings
        if sensor_type.lower() == "temperature"
        and sensor_id.lower().startswith(_GPU_ID_PREFIXES)
        and _plausible(value)
    ]
    if not gpu:
        return None

    # 优先核心温度，和 nvidia-smi 的口径一致；没有核心温度再看热点。
    for keyword in ("gpu core", "hot spot", "hotspot"):
        values = [value for name, value in gpu if keyword in name]
        if values:
            return max(values)

    # 排除显存/供电温度这类容易虚高的传感器，再退而求其次。
    values = [
        value for name, value in gpu
        if "memory" not in name and "vrm" not in name
    ]
    if values:
        return max(values)
    return max(value for _, value in gpu)


def _read_gpu_pynvml() -> Optional[float]:
    """没有 nvidia-smi 命令时的备用方案。"""
    try:
        import pynvml
    except Exception:
        return None

    initialized = False
    try:
        pynvml.nvmlInit()
        initialized = True

        values = []
        for index in range(int(pynvml.nvmlDeviceGetCount())):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            value = float(
                pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            )
            if _plausible(value):
                values.append(value)
        return max(values) if values else None
    except Exception:
        return None
    finally:
        if initialized:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass


# ---------------------------------------------------------------- 对外接口

def read_cpu_temperature() -> Optional[float]:
    """读 CPU 温度（°C）。读不到返回 None，绝不抛异常。"""
    return _first_reading(_read_cpu_lhm, _read_cpu_psutil)


def read_gpu_temperature() -> Optional[float]:
    """读 GPU 温度（°C）。读不到返回 None，绝不抛异常。"""
    return _first_reading(_read_gpu_nvidia_smi, _read_gpu_lhm, _read_gpu_pynvml)


def read_cpu_usage() -> Optional[float]:
    """读 CPU 总占用率（0~100）。读不到返回 None，绝不抛异常。"""
    try:
        value = _read_cpu_usage_lhm()
        if value is not None:
            return value
        return _read_cpu_usage_psutil()
    except Exception:
        return None


def read_temperatures(config: Optional[dict] = None) -> Dict[str, Optional[float]]:
    """读一次温度。CPU 占用请用 read_cpu_usage()，不要混进这个字典。"""
    cfg = config if isinstance(config, dict) else {}
    result: Dict[str, Optional[float]] = {"cpu": None, "gpu": None}

    for key, reader in (("cpu", read_cpu_temperature), ("gpu", read_gpu_temperature)):
        try:
            enabled = bool(cfg.get(key, True))
        except Exception:
            enabled = True
        if not enabled:
            continue
        try:
            value = reader()
        except Exception:
            value = None
        result[key] = float(value) if _plausible(value) else None

    return result


# ---------------------------------------------------------------- 自检

def _format_temperature(value: Optional[float]) -> str:
    return f"{value:.1f} °C" if _plausible(value) else "读不到（None）"


def _format_percent(value: Optional[float]) -> str:
    return f"{value:.1f} %" if _as_percent(value) is not None else "读不到（None）"


if __name__ == "__main__":
    print("temguard 传感器自检")
    print("-" * 56)
    print(f"LibreHardwareMonitor：{LHM_URL}")

    cpu = read_cpu_temperature()
    gpu = read_gpu_temperature()
    usage = read_cpu_usage()

    print(f"CPU 温度：{_format_temperature(cpu)}")
    print(f"GPU 温度：{_format_temperature(gpu)}")
    print(f"CPU 占用：{_format_percent(usage)}")

    if cpu is None or usage is None:
        print("  提示：启动 LibreHardwareMonitor（管理员身份），并打开")
        print("        Options → Remote Web Server → Run（默认端口 8085）。")
    if gpu is None:
        print("  提示：NVIDIA 显卡确认 nvidia-smi 可用；")
        print("        AMD/Intel 显卡确认 LibreHardwareMonitor 正在运行。")

    print("-" * 56)
    print("读不到不是错误：主程序会继续运行，只是跳过这一项。")
