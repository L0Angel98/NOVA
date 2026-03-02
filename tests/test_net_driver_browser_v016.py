import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest
from unittest.mock import patch

from nova.cap.http_cap import HttpCapError, http_get
from nova.cap.net import browser as browser_driver


class _BrowserDriverHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"<html><head><title>NOVA Browser</title></head><body><h1>OK</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class NovaBrowserNetDriverV016Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _BrowserDriverHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def tearDown(self) -> None:
        browser_driver._reset_browser_for_tests()

    def test_browser_driver_example_domain_and_keepalive(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "browser"}, clear=False):
            browser_driver._reset_browser_for_tests()
            try:
                out1 = http_get("https://example.com", None, 15)
                out2 = http_get("https://example.com", None, 15)
            except HttpCapError as exc:
                msg = exc.msg.lower()
                if "requires playwright" in msg or "install chromium" in msg:
                    self.skipTest(exc.msg)
                self.skipTest(f"browser net unavailable in this env: {exc.code} {exc.msg}")

        self.assertEqual(out1["st"], 200)
        self.assertIn("Example Domain", out1["bd"])
        self.assertEqual(out2["st"], 200)
        self.assertIn("Example Domain", out2["bd"])

        state = browser_driver._debug_browser_state()
        self.assertEqual(state["starts"], 1)
        self.assertTrue(state["alive"])

    def test_browser_driver_stays_stable_across_request_threads(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "browser"}, clear=False):
            browser_driver._reset_browser_for_tests()
            for _ in range(6):
                out_holder: dict[str, object] = {}
                err_holder: dict[str, Exception] = {}

                def _run() -> None:
                    try:
                        out_holder["out"] = http_get(f"{self.base_url}/thread", None, 10)
                    except Exception as exc:  # pragma: no cover - captured assertion path
                        err_holder["err"] = exc

                t = threading.Thread(target=_run)
                t.start()
                t.join(timeout=20)
                self.assertFalse(t.is_alive(), "browser request thread must finish")

                if "err" in err_holder:
                    err = err_holder["err"]
                    if isinstance(err, HttpCapError):
                        msg = err.msg.lower()
                        if "requires playwright" in msg or "install chromium" in msg:
                            self.skipTest(err.msg)
                    self.fail(f"browser driver failed across threads: {err}")

                out = out_holder.get("out")
                self.assertIsInstance(out, dict)
                self.assertEqual(int(out["st"]), 200)
                self.assertIn("NOVA Browser", str(out["bd"]))

        state = browser_driver._debug_browser_state()
        self.assertEqual(state["starts"], 1)
        self.assertTrue(state["alive"])


if __name__ == "__main__":
    unittest.main()
