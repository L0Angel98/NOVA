import json
from pathlib import Path
import threading
import time
import unittest
import urllib.request
import urllib.error

from nova.runtime import NovaRuntime, run_server


ROOT = Path(__file__).resolve().parents[1]
DEMO_APP = ROOT / "demo" / "app.nv"


class NovaRuntimeTests(unittest.TestCase):
    def test_dispatch_crud_flow(self) -> None:
        runtime = NovaRuntime.from_file(DEMO_APP, capabilities={"db"})

        status, payload = runtime.dispatch("POST", "/items", {"content-type": "application/json"}, {"name": "alpha"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        item_id = payload["data"]["id"]

        status, payload = runtime.dispatch("GET", "/items?n=1", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["data"]["items"]), 1)

        status, payload = runtime.dispatch("PUT", f"/items/{item_id}", {}, {"name": "beta"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["count"], 1)

        status, payload = runtime.dispatch("DELETE", f"/items/{item_id}", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["deleted"], 1)

        status, payload = runtime.dispatch("GET", "/items", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["items"], [])

    def test_dispatch_context_and_error_mapping(self) -> None:
        runtime = NovaRuntime.from_file(DEMO_APP, capabilities={"db"})

        status, payload = runtime.dispatch("GET", "/ping", {"x-test": "1"}, None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["method"], "GET")
        self.assertTrue(payload["data"]["request_id"].startswith("req-"))

        status, payload = runtime.dispatch("POST", "/items", {}, None)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "BAD_REQUEST")

        status, payload = runtime.dispatch("GET", "/missing", {}, None)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "ROUTE_NOT_FOUND")

        status, payload = runtime.dispatch("POST", "/ping", {}, None)
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_server_is_runnable(self) -> None:
        server = run_server(DEMO_APP, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)

        host, port = server.server_address
        url = f"http://{host}:{port}/ping"

        with urllib.request.urlopen(url, timeout=2) as res:
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode("utf-8"))
            self.assertTrue(data["ok"])

        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
