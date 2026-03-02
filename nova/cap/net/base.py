from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


NetPayload = Dict[str, Any]


@dataclass(frozen=True)
class NetDriverError(Exception):
    code: str
    msg: str

    def __str__(self) -> str:
        return f"{self.code}: {self.msg}"


def ensure_http_payload(payload: Any, *, driver: str) -> NetPayload:
    if not isinstance(payload, dict):
        raise NetDriverError("NET_REQ", f"net driver '{driver}' returned non-object payload")

    if "st" not in payload or "hd" not in payload or "bd" not in payload:
        raise NetDriverError("NET_REQ", f"net driver '{driver}' returned payload missing st/hd/bd")

    try:
        status = int(payload.get("st"))
    except Exception as exc:
        raise NetDriverError("NET_REQ", f"net driver '{driver}' returned invalid st") from exc

    headers_raw = payload.get("hd")
    if not isinstance(headers_raw, dict):
        raise NetDriverError("NET_REQ", f"net driver '{driver}' returned invalid hd")
    headers = {str(k): str(v) for k, v in headers_raw.items()}

    body = payload.get("bd")
    body_text = "" if body is None else str(body)

    return {"st": status, "hd": headers, "bd": body_text}

