from __future__ import annotations

import atexit
from dataclasses import dataclass
from itertools import count
import queue
import threading
from typing import Any, Dict, Optional

from .base import NetDriverError, NetPayload, ensure_http_payload


_RETRY_LIMIT = 1
_BROWSER_LOCK = threading.Lock()
_BROWSER: Optional["BrowserNet"] = None
_ATEXIT_REGISTERED = False
_STOP = object()


def http_get(url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
    return _get_browser().call_get(url, headers, timeout)


@dataclass(frozen=True)
class _BrowserRequest:
    rid: int
    url: str
    headers: Dict[str, str]
    timeout: float
    waiter: "queue.Queue[Dict[str, Any]]"


class BrowserNet:
    def __init__(self) -> None:
        self._call_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._worker_ready = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._req_q: "queue.Queue[object]" = queue.Queue()
        self._next_id = count(1)
        self._starts = 0
        self._alive = False
        self._last_err = ""
        self._boot_err: Optional[NetDriverError] = None

    def call_get(self, url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
        with self._call_lock:
            for attempt in range(_RETRY_LIMIT + 1):
                try:
                    return self._call_get_once(url, headers, timeout)
                except NetDriverError as exc:
                    if attempt < _RETRY_LIMIT and self._is_retryable(exc):
                        self._restart()
                        continue
                    raise
            raise NetDriverError("NET_REQ", "browser worker failed")

    def close(self) -> None:
        with self._call_lock:
            self._stop_worker()

    def state(self) -> Dict[str, Any]:
        with self._state_lock:
            tid = self._worker_thread.ident if self._worker_thread is not None else None
            return {"starts": self._starts, "alive": self._alive, "tid": tid, "last_err": self._last_err}

    def _call_get_once(self, url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
        self._start_if_needed()
        req_id = next(self._next_id)
        waiter: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=1)
        req = _BrowserRequest(rid=req_id, url=url, headers=dict(headers), timeout=timeout, waiter=waiter)

        try:
            self._req_q.put(req, timeout=1.0)
        except Exception as exc:
            raise NetDriverError("NET_REQ", f"browser worker queue failed: {exc}") from exc

        wait_s = max(float(timeout) + 5.0, 10.0)
        try:
            data = waiter.get(timeout=wait_s)
        except queue.Empty as exc:
            raise NetDriverError("NET_REQ", "browser worker response timeout") from exc

        if not bool(data.get("ok")):
            msg = str(data.get("msg") or "browser worker request failed")
            st = data.get("st")
            if isinstance(st, int) and st > 0:
                msg = f"{msg} (st={st})"
            raise NetDriverError("NET_REQ", msg)

        return ensure_http_payload(
            {"st": data.get("st"), "hd": data.get("hd"), "bd": data.get("bd")},
            driver="browser",
        )

    def _start_if_needed(self) -> None:
        with self._state_lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return
            self._worker_ready = threading.Event()
            self._boot_err = None
            self._req_q = queue.Queue()
            self._alive = False
            self._last_err = ""
            self._worker_thread = threading.Thread(target=self._worker_loop, name="nova-net-browser", daemon=True)
            self._worker_thread.start()

        started = self._worker_ready.wait(timeout=15.0)
        if not started:
            self._stop_worker()
            raise NetDriverError("NET_REQ", "browser worker startup timeout")

        with self._state_lock:
            boot_err = self._boot_err
        if boot_err is not None:
            raise boot_err

    def _restart(self) -> None:
        self._stop_worker()

    def _stop_worker(self) -> None:
        with self._state_lock:
            thread = self._worker_thread
            req_q = self._req_q
            self._worker_thread = None
            self._alive = False
        if thread is None:
            return
        try:
            req_q.put(_STOP, timeout=0.1)
        except Exception:
            pass
        thread.join(timeout=3.0)
        self._fail_pending(req_q, "browser worker stopped")

    def _worker_loop(self) -> None:
        pw = None
        browser = None
        context = None

        try:
            try:
                from playwright.sync_api import sync_playwright
            except Exception as exc:
                err = NetDriverError(
                    "NET_REQ",
                    "net driver 'browser' requires Playwright. install dependency 'playwright'",
                )
                self._set_boot_err(err)
                self._set_last_err(str(exc))
                return

            try:
                pw = sync_playwright().start()
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context()
            except Exception as exc:
                err = _map_browser_exc(exc)
                self._set_boot_err(err)
                self._set_last_err(str(exc))
                return

            with self._state_lock:
                self._starts += 1
                self._alive = True
                self._boot_err = None
            self._worker_ready.set()

            while True:
                item = self._req_q.get()
                if item is _STOP:
                    break
                if not isinstance(item, _BrowserRequest):
                    continue
                item.waiter.put(self._perform_get(context, item))
        except Exception as exc:  # pragma: no cover - defensive
            self._set_last_err(str(exc))
        finally:
            self._safe_close(context)
            self._safe_close(browser)
            self._safe_close(pw, method="stop")
            with self._state_lock:
                self._alive = False
            self._worker_ready.set()
            self._fail_pending(self._req_q, "browser worker stopped")

    def _perform_get(self, context: Any, req: _BrowserRequest) -> Dict[str, Any]:
        timeout_ms = _to_timeout_ms(req.timeout)
        page = None
        try:
            context.set_extra_http_headers(dict(req.headers))
            page = context.new_page()
            response = page.goto(req.url, wait_until="domcontentloaded", timeout=timeout_ms)
            status = int(response.status) if response is not None else 0
            headers_out = dict(response.headers) if response is not None else {}
            body = page.content()
            return {"id": req.rid, "ok": True, "st": status, "hd": headers_out, "bd": body}
        except Exception as exc:
            mapped = _map_browser_exc(exc)
            self._set_last_err(mapped.msg)
            return {"id": req.rid, "ok": False, "st": 0, "msg": mapped.msg}
        finally:
            if page is not None:
                self._safe_close(page)

    def _fail_pending(self, req_q: "queue.Queue[object]", message: str) -> None:
        while True:
            try:
                item = req_q.get_nowait()
            except queue.Empty:
                return
            if isinstance(item, _BrowserRequest):
                item.waiter.put({"id": item.rid, "ok": False, "st": 0, "msg": message})

    def _set_boot_err(self, err: NetDriverError) -> None:
        with self._state_lock:
            self._boot_err = err
            self._alive = False
        self._worker_ready.set()

    def _set_last_err(self, message: str) -> None:
        with self._state_lock:
            self._last_err = message

    def _safe_close(self, obj: Any, method: str = "close") -> None:
        if obj is None:
            return
        fn = getattr(obj, method, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass

    def _is_retryable(self, exc: NetDriverError) -> bool:
        lowered = exc.msg.lower()
        if "requires playwright" in lowered or "install chromium" in lowered:
            return False
        return (
            "worker" in lowered
            or "timeout" in lowered
            or "greenlet" in lowered
            or "cannot switch to a different thread" in lowered
            or "target closed" in lowered
            or "closed" in lowered
        )


def _to_timeout_ms(timeout_s: float) -> int:
    timeout = float(timeout_s)
    if timeout <= 0:
        raise NetDriverError("NET_INPUT", "timeout must be > 0")
    return int(timeout * 1000.0)


def _map_browser_exc(exc: Exception) -> NetDriverError:
    msg = str(exc).strip()
    lower = msg.lower()

    if "playwright" in lower and "install" in lower and "chromium" in lower:
        return NetDriverError("NET_REQ", "net driver 'browser' requires Chromium. run: python -m playwright install chromium")
    if "executable doesn't exist" in lower and "chromium" in lower:
        return NetDriverError("NET_REQ", "net driver 'browser' requires Chromium. run: python -m playwright install chromium")
    if "cannot switch to a different thread" in lower:
        return NetDriverError("NET_REQ", f"browser worker thread error: {msg}")
    if "timeout" in lower:
        return NetDriverError("NET_REQ", f"browser.get timeout: {msg}")
    return NetDriverError("NET_REQ", f"browser.get failed: {msg}")


def _get_browser() -> BrowserNet:
    global _BROWSER, _ATEXIT_REGISTERED
    with _BROWSER_LOCK:
        if _BROWSER is None:
            _BROWSER = BrowserNet()
        if not _ATEXIT_REGISTERED:
            atexit.register(_shutdown_browser)
            _ATEXIT_REGISTERED = True
        return _BROWSER


def _shutdown_browser() -> None:
    with _BROWSER_LOCK:
        browser = _BROWSER
    if browser is not None:
        browser.close()


def _reset_browser_for_tests() -> None:
    global _BROWSER
    with _BROWSER_LOCK:
        browser = _BROWSER
        _BROWSER = None
    if browser is not None:
        browser.close()


def _debug_browser_state() -> Dict[str, Any]:
    with _BROWSER_LOCK:
        browser = _BROWSER
    if browser is None:
        return {"starts": 0, "alive": False}
    return browser.state()
