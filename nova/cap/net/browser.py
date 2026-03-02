from __future__ import annotations

import atexit
import threading
from typing import Any, Dict, Optional

from .base import NetDriverError, NetPayload, ensure_http_payload


_RETRY_LIMIT = 1
_BROWSER_LOCK = threading.Lock()
_BROWSER: Optional["BrowserNet"] = None
_ATEXIT_REGISTERED = False


def http_get(url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
    return _get_browser().get(url, headers, timeout)


class BrowserNet:
    def __init__(self) -> None:
        self._call_lock = threading.Lock()
        self._pw = None
        self._browser = None
        self._context = None
        self._starts = 0

    def get(self, url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
        with self._call_lock:
            for attempt in range(_RETRY_LIMIT + 1):
                try:
                    return self._get_once(url, headers, timeout)
                except NetDriverError as exc:
                    if attempt < _RETRY_LIMIT and self._is_retryable(exc):
                        self._restart()
                        continue
                    raise
            raise NetDriverError("NET_REQ", "browser worker request failed")

    def close(self) -> None:
        with self._call_lock:
            self._shutdown()

    def state(self) -> Dict[str, Any]:
        browser = self._browser
        alive = bool(browser is not None and getattr(browser, "is_connected", lambda: False)())
        return {"starts": self._starts, "alive": alive}

    def _get_once(self, url: str, headers: Dict[str, str], timeout: float) -> NetPayload:
        self._start_if_needed()
        timeout_ms = _to_timeout_ms(timeout)

        if self._context is None:
            raise NetDriverError("NET_REQ", "browser context is not ready")

        # Reuse one context and update headers for the next page request.
        self._context.set_extra_http_headers(dict(headers))
        page = self._context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            status = int(response.status) if response is not None else 0
            headers_out = dict(response.headers) if response is not None else {}
            body = page.content()
        except Exception as exc:
            raise _map_browser_exc(exc) from exc
        finally:
            try:
                page.close()
            except Exception:
                pass

        return ensure_http_payload({"st": status, "hd": headers_out, "bd": body}, driver="browser")

    def _start_if_needed(self) -> None:
        if self._browser is not None and self._context is not None and self._browser.is_connected():
            return

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise NetDriverError(
                "NET_REQ",
                "net driver 'browser' requires Playwright. install dependency 'playwright'",
            ) from exc

        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context()
            self._starts += 1
        except Exception as exc:
            self._shutdown()
            raise _map_browser_exc(exc) from exc

    def _restart(self) -> None:
        self._shutdown()

    def _shutdown(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

    def _is_retryable(self, exc: NetDriverError) -> bool:
        lowered = exc.msg.lower()
        if "requires playwright" in lowered or "install chromium" in lowered:
            return False
        return "browser" in lowered or "target closed" in lowered or "closed" in lowered


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

