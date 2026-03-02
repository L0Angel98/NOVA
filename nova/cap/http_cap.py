from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import requests


@dataclass(frozen=True)
class HttpCapError(Exception):
    code: str
    msg: str

    def __str__(self) -> str:
        return f"{self.code}: {self.msg}"


def http_get(url: Any, h: Any = None, t: Any = None) -> Dict[str, Any]:
    target = str(url).strip()
    if target == "":
        raise HttpCapError("NET_INPUT", "http.get requires non-empty url")

    timeout = 8.0
    if t is not None:
        try:
            timeout = float(t)
        except Exception as exc:  # pragma: no cover - defensive
            raise HttpCapError("NET_INPUT", f"invalid timeout value: {t}") from exc
        if timeout <= 0:
            raise HttpCapError("NET_INPUT", "timeout must be > 0")

    headers: Dict[str, str] = {"User-Agent": "nova/0.1.3"}
    if h is not None:
        if not isinstance(h, dict):
            raise HttpCapError("NET_INPUT", "headers must be object")
        for key, value in h.items():
            headers[str(key)] = str(value)

    try:
        response = requests.get(target, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise HttpCapError("NET_REQ", str(exc)) from exc

    return {
        "st": int(response.status_code),
        "hd": dict(response.headers.items()),
        "bd": response.text,
    }

