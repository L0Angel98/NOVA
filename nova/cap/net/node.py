from __future__ import annotations

import atexit
from collections import deque
import json
from itertools import count
from pathlib import Path
import queue
import shutil
import subprocess
import threading
from typing import Any, Dict, Optional

from .base import NetDriverError, NetPayload, ensure_http_payload


_NODE_MIN_MAJOR = 18
_RETRY_LIMIT = 1
_WORKER_LOCK = threading.Lock()
_WORKER: Optional["NodeNetWorker"] = None
_ATEXIT_REGISTERED = False


def http_get(url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
    return _get_worker().call_get(url, headers, timeout)


class NodeNetWorker:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._next_id = count(1)
        self._pending: Dict[int, "queue.Queue[Dict[str, Any]]"] = {}
        self._pending_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._stderr_lock = threading.Lock()
        self._stderr_lines: deque[str] = deque(maxlen=40)
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._starts = 0

    def call_get(self, url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
        with self._call_lock:
            for attempt in range(_RETRY_LIMIT + 1):
                try:
                    response = self._call_get_once(url, headers, timeout)
                    if bool(response.get("ok")):
                        return ensure_http_payload(
                            {"st": response.get("st"), "hd": response.get("hd"), "bd": response.get("bd")},
                            driver="node",
                        )

                    msg = str(response.get("msg") or "node worker request failed")
                    st = response.get("st")
                    if isinstance(st, int) and st > 0:
                        msg = f"{msg} (st={st})"
                    raise NetDriverError("NET_REQ", msg)
                except NetDriverError as exc:
                    if attempt < _RETRY_LIMIT and self._is_retryable(exc):
                        self._restart()
                        continue
                    raise

            raise NetDriverError("NET_REQ", "node worker request failed")

    def close(self) -> None:
        with self._call_lock:
            self._terminate_process()
            self._fail_pending("node worker closed")

    def state(self) -> Dict[str, Any]:
        proc = self._proc
        alive = bool(proc is not None and proc.poll() is None)
        pid = proc.pid if proc is not None else None
        with self._stderr_lock:
            stderr_tail = list(self._stderr_lines)
        return {"starts": self._starts, "pid": pid, "alive": alive, "stderr": stderr_tail}

    def _call_get_once(self, url: str, headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
        self._start_if_needed()
        req_id = next(self._next_id)
        payload = {"id": req_id, "op": "get", "u": url, "h": headers, "t": timeout}
        waiter: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1)

        with self._pending_lock:
            self._pending[req_id] = waiter

        try:
            self._write_jsonl(payload)
        except Exception:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise

        wait_s = max(float(timeout) + 5.0, 10.0)
        try:
            return waiter.get(timeout=wait_s)
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise NetDriverError("NET_REQ", "node worker response timeout") from exc

    def _write_jsonl(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with self._io_lock:
            proc = self._proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                raise NetDriverError("NET_REQ", "node worker is not running")
            try:
                proc.stdin.write(line + "\n")
                proc.stdin.flush()
            except OSError as exc:
                raise NetDriverError("NET_REQ", f"node worker write failed: {exc}") from exc

    def _start_if_needed(self) -> None:
        with self._io_lock:
            if self._proc is not None and self._proc.poll() is None:
                return

            node_bin = _resolve_node_executable()
            script = Path(__file__).with_name("node_worker.mjs")
            if not script.exists():
                raise NetDriverError("NET_REQ", f"node worker script not found: {script}")

            try:
                proc = subprocess.Popen(
                    [node_bin, str(script)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
            except OSError as exc:
                raise NetDriverError("NET_REQ", f"cannot start node worker: {exc}") from exc

            self._proc = proc
            self._starts += 1
            self._stdout_thread = threading.Thread(target=self._stdout_loop, name="nova-net-node-stdout", daemon=True)
            self._stderr_thread = threading.Thread(target=self._stderr_loop, name="nova-net-node-stderr", daemon=True)
            self._stdout_thread.start()
            self._stderr_thread.start()

    def _restart(self) -> None:
        self._terminate_process()

    def _terminate_process(self) -> None:
        with self._io_lock:
            proc = self._proc
            self._proc = None

        if proc is None:
            return

        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except Exception:
                proc.kill()
                proc.wait(timeout=1.5)

        for handle in (proc.stdin, proc.stdout, proc.stderr):
            if handle is None:
                continue
            try:
                handle.close()
            except Exception:
                pass

    def _stdout_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return

        for line in proc.stdout:
            text = line.strip()
            if text == "":
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                self._push_stderr(f"node worker stdout invalid json: {text[:200]}")
                continue

            req_id = data.get("id")
            if not isinstance(req_id, int):
                self._push_stderr(f"node worker response missing id: {text[:200]}")
                continue

            with self._pending_lock:
                waiter = self._pending.pop(req_id, None)
            if waiter is not None:
                waiter.put(data)

        self._fail_pending("node worker stdout closed")

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return

        for line in proc.stderr:
            text = line.strip()
            if text != "":
                self._push_stderr(text[:300])

    def _push_stderr(self, text: str) -> None:
        with self._stderr_lock:
            self._stderr_lines.append(text)

    def _fail_pending(self, message: str) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            waiter.put({"id": -1, "ok": False, "st": 0, "msg": message})

    def _is_retryable(self, exc: NetDriverError) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return True
        lowered = exc.msg.lower()
        return "worker" in lowered or "timeout" in lowered or "write failed" in lowered


def _get_worker() -> NodeNetWorker:
    global _WORKER, _ATEXIT_REGISTERED
    with _WORKER_LOCK:
        if _WORKER is None:
            _WORKER = NodeNetWorker()
        if not _ATEXIT_REGISTERED:
            atexit.register(_shutdown_worker)
            _ATEXIT_REGISTERED = True
        return _WORKER


def _shutdown_worker() -> None:
    with _WORKER_LOCK:
        worker = _WORKER
    if worker is not None:
        worker.close()


def _reset_worker_for_tests() -> None:
    global _WORKER
    with _WORKER_LOCK:
        worker = _WORKER
        _WORKER = None
    if worker is not None:
        worker.close()


def _debug_worker_state() -> Dict[str, Any]:
    with _WORKER_LOCK:
        worker = _WORKER
    if worker is None:
        return {"starts": 0, "pid": None, "alive": False, "stderr": []}
    return worker.state()


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
