from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict

from .net import browser as browser_driver
from .net import node as node_driver
from .net import py as py_driver
from .net.base import NetDriverError, ensure_http_payload


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

    headers: Dict[str, str] = {"User-Agent": "nova/0.1.6"}
    if h is not None:
        if not isinstance(h, dict):
            raise HttpCapError("NET_INPUT", "headers must be object")
        for key, value in h.items():
            headers[str(key)] = str(value)

    driver_name = _resolve_driver_name()
    driver = _resolve_driver(driver_name)

    try:
        payload = driver(target, headers, timeout)
        return ensure_http_payload(payload, driver=driver_name)
    except NetDriverError as exc:
        raise HttpCapError(exc.code, exc.msg) from exc


def _resolve_driver_name() -> str:
    raw = os.environ.get("NOVA_NET_DRIVER", "py")
    name = str(raw).strip().lower()
    if name == "":
        return "py"
    return name


def _resolve_driver(name: str):
    if name == "py":
        return py_driver.http_get
    if name == "node":
        return node_driver.http_get
    if name == "browser":
        return browser_driver.http_get
    raise HttpCapError("NET_INPUT", f"unsupported net driver '{name}' (expected py|node|browser)")

