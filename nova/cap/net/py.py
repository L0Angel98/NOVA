from __future__ import annotations

from typing import Dict

import requests

from .base import NetDriverError, NetPayload, ensure_http_payload


def http_get(url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise NetDriverError("NET_REQ", str(exc)) from exc

    return ensure_http_payload(
        {
            "st": int(response.status_code),
            "hd": dict(response.headers.items()),
            "bd": response.text,
        },
        driver="py",
    )

