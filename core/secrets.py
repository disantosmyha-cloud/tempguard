"""Windows DPAPI 密钥保险箱。

配置文件里写：

    api_key: "${secret:astrbot_api_key}"

密钥本身存放在 `secrets.dat`，用当前 Windows 用户的 DPAPI 加密。
只能由同一 Windows 用户解密；换用户/换机器无法读取。

命令行：

    python -m core.secrets set alertd_token
    python -m core.secrets list
"""

from __future__ import annotations

import base64
import ctypes
import getpass
import json
import os
import re
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "secrets.dat"
_PLACEHOLDER = re.compile(r"^\$\{secret:([A-Za-z0-9_.-]+)\}$")


class SecretError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretError("DPAPI 仅支持 Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(out_blob),
    ):
        raise SecretError("CryptProtectData 失败")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretError("DPAPI 仅支持 Windows")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_blob = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out_blob = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(out_blob),
    ):
        raise SecretError("CryptUnprotectData 失败")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _read_vault() -> dict[str, str]:
    if not VAULT.exists():
        return {}
    try:
        return json.loads(VAULT.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SecretError(f"无法读取 secrets.dat：{exc}") from exc


def _write_vault(vault: dict[str, str]) -> None:
    VAULT.parent.mkdir(parents=True, exist_ok=True)
    tmp = VAULT.with_suffix(".tmp")
    tmp.write_text(json.dumps(vault, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(VAULT)


def set_secret(name: str, value: str) -> None:
    name = str(name).strip()
    if not name:
        raise SecretError("secret 名称不能为空")
    vault = _read_vault()
    vault[name] = base64.b64encode(_protect(str(value).encode("utf-8"))).decode("ascii")
    _write_vault(vault)


def get_secret(name: str) -> str:
    vault = _read_vault()
    encoded = vault.get(str(name))
    if not encoded:
        raise SecretError(f"secrets.dat 里没有 {name}")
    return _unprotect(base64.b64decode(encoded)).decode("utf-8")


def resolve_value(value: Any) -> Any:
    if isinstance(value, str):
        match = _PLACEHOLDER.match(value.strip())
        if match:
            return get_secret(match.group(1))
        return value
    if isinstance(value, list):
        return [resolve_value(item) for item in value]
    if isinstance(value, dict):
        return {key: resolve_value(item) for key, item in value.items()}
    return value


def resolve_config(config: Any) -> Any:
    return resolve_value(config)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in ("set", "list"):
        print("usage: python -m core.secrets set <name> | list")
        return 2
    if args[0] == "list":
        print("\n".join(sorted(_read_vault())))
        return 0
    if len(args) != 2:
        print("usage: python -m core.secrets set <name>")
        return 2
    value = getpass.getpass(f"{args[1]} value: ")
    if not value:
        print("empty secret; not saved")
        return 1
    set_secret(args[1], value)
    print(f"saved {args[1]} to {VAULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
