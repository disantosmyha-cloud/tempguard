"""HTTP 小工具，只用标准库，避免给 temguard 增加依赖。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional, Tuple


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 5.0,
    headers: Optional[dict[str, str]] = None,
) -> Tuple[bool, Any, str]:
    """返回 (HTTP 2xx, 解析后的 JSON 或原始文本, 错误信息)。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=request_headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            if 200 <= response.status < 300:
                try:
                    return True, json.loads(raw), ""
                except json.JSONDecodeError:
                    return True, raw, ""
            return False, raw, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        return False, detail, f"HTTP {exc.code}"
    except Exception as exc:
        return False, "", str(exc)[:300]
