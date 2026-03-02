import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import shutil
import threading
import time
import unittest
from unittest.mock import patch

from nova.cap.http_cap import HttpCapError, http_get
from nova.cap.net.base import NetDriverError


class _NetDriverHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/blocked"):
            body = b"blocked"
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = b"<html><head><title>NOVA</title></head><body><h1>OK</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Net-Test", "yes")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class NovaNetDriverV015Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _NetDriverHandler)
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

    def test_default_driver_is_py(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVA_NET_DRIVER", None)
            with patch("nova.cap.net.py.http_get", return_value={"st": 200, "hd": {}, "bd": "ok"}) as py_get:
                with patch("nova.cap.net.node.http_get", return_value={"st": 200, "hd": {}, "bd": "bad"}) as node_get:
                    with patch("nova.cap.net.browser.http_get", return_value={"st": 200, "hd": {}, "bd": "bad2"}) as browser_get:
                        out = http_get(f"{self.base_url}/ok")
        self.assertEqual(out["st"], 200)
        self.assertEqual(out["bd"], "ok")
        py_get.assert_called_once()
        node_get.assert_not_called()
        browser_get.assert_not_called()

    def test_node_driver_is_selected_by_env(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "node"}, clear=False):
            with patch("nova.cap.net.node.http_get", return_value={"st": 200, "hd": {}, "bd": "ok-node"}) as node_get:
                out = http_get(f"{self.base_url}/ok")
        self.assertEqual(out["bd"], "ok-node")
        node_get.assert_called_once()

    def test_browser_driver_is_selected_by_env(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "browser"}, clear=False):
            with patch("nova.cap.net.browser.http_get", return_value={"st": 200, "hd": {}, "bd": "ok-browser"}) as browser_get:
                out = http_get(f"{self.base_url}/ok")
        self.assertEqual(out["bd"], "ok-browser")
        browser_get.assert_called_once()

    def test_invalid_driver_name_is_explicit(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "bad"}, clear=False):
            with self.assertRaises(HttpCapError) as ctx:
                http_get(f"{self.base_url}/ok")
        self.assertEqual(ctx.exception.code, "NET_INPUT")
        self.assertIn("expected py|node|browser", ctx.exception.msg)

    def test_node_driver_missing_node_is_explicit(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "node"}, clear=False):
            with patch(
                "nova.cap.net.node._resolve_node_executable",
                side_effect=NetDriverError("NET_REQ", "net driver 'node' requires Node.js 18+"),
            ):
                with self.assertRaises(HttpCapError) as ctx:
                    http_get(f"{self.base_url}/ok")
        self.assertEqual(ctx.exception.code, "NET_REQ")
        self.assertIn("Node.js 18+", ctx.exception.msg)

    def test_py_driver_propagates_non_200_status(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "py"}, clear=False):
            out = http_get(f"{self.base_url}/blocked")
        self.assertEqual(out["st"], 403)
        self.assertEqual(out["bd"], "blocked")

    @unittest.skipUnless(shutil.which("node"), "node not available")
    def test_node_driver_propagates_non_200_status(self) -> None:
        with patch.dict(os.environ, {"NOVA_NET_DRIVER": "node"}, clear=False):
            out = http_get(f"{self.base_url}/blocked")
        self.assertEqual(out["st"], 403)
        self.assertEqual(out["bd"], "blocked")


if __name__ == "__main__":
    unittest.main()

