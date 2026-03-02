from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Dict

from .base import NetDriverError, NetPayload, ensure_http_payload


_NODE_MIN_MAJOR = 18


def http_get(url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
    node_bin = _resolve_node_executable()
    script = Path(__file__).with_name("node_fetch.mjs")
    payload = json.dumps({"url": url, "h": headers, "t": timeout}, ensure_ascii=False)

    try:
        proc = subprocess.run(
            [node_bin, str(script)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise NetDriverError("NET_REQ", f"node driver execution failed: {exc}") from exc

    raw_out = (proc.stdout or "").strip()
    if raw_out == "":
        detail = (proc.stderr or "").strip()
        if detail == "":
            detail = "empty stdout"
        raise NetDriverError("NET_REQ", f"node driver produced no JSON output: {detail}")

    try:
        data = json.loads(raw_out)
    except json.JSONDecodeError as exc:
        raise NetDriverError("NET_REQ", f"node driver returned invalid JSON: {raw_out[:160]}") from exc

    if isinstance(data, dict) and bool(data.get("err")):
        msg = str(data.get("msg") or "node fetch error")
        st = data.get("st")
        if isinstance(st, int) and st > 0:
            msg = f"{msg} (st={st})"
        raise NetDriverError("NET_REQ", msg)

    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()
        if detail == "":
            detail = f"exit code {proc.returncode}"
        raise NetDriverError("NET_REQ", f"node driver failed: {detail}")

    return ensure_http_payload(data, driver="node")


def _resolve_node_executable() -> str:
    node_bin = shutil.which("node")
    if node_bin is None:
        raise NetDriverError("NET_REQ", "net driver 'node' requires Node.js 18+")

    try:
        proc = subprocess.run(
            [node_bin, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise NetDriverError("NET_REQ", f"net driver 'node' requires Node.js 18+: {exc}") from exc

    version_text = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        raise NetDriverError("NET_REQ", "net driver 'node' requires Node.js 18+")

    major = _parse_major(version_text)
    if major < _NODE_MIN_MAJOR:
        raise NetDriverError("NET_REQ", "net driver 'node' requires Node.js 18+")

    return node_bin


def _parse_major(version_text: str) -> int:
    text = version_text.strip()
    if text.startswith("v"):
        text = text[1:]
    head = text.split(".", 1)[0]
    try:
        return int(head)
    except Exception:
        return -1
