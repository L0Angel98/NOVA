import json
from pathlib import Path
import threading
import time
import unittest
import urllib.request

from nova.parser import parse_toon
from nova.runtime import NovaRuntime, run_server
from nova.toon import ToonDecodeError, decode_toon, encode_toon, json_size_bytes, toon_size_bytes


ROOT = Path(__file__).resolve().parents[1]
DEMO_APP = ROOT / "demo" / "app.nv"


class NovaToonTests(unittest.TestCase):
    def test_toon_roundtrip_tabular_array(self) -> None:
        data = [
            {"id": 1, "name": "Ada", "tags": ["math", "logic"], "active": True},
            {"id": 2, "name": "Lin", "tags": ["systems", "perf"], "active": False},
        ]

        encoded = encode_toon(data)
        decoded = decode_toon(encoded)
        self.assertEqual(decoded, data)

    def test_toon_n_validation_rejects_wrong_array_length(self) -> None:
        text = """@toon v1
@type table
@rows 1
|id|tags[2]|
|1|[\"x\"]|
"""
        with self.assertRaises(ToonDecodeError):
            decode_toon(text)

    def test_toon_payload_smaller_than_json_for_tabular_rows(self) -> None:
        rows = [
            {
                "id": i,
                "name": f"item-{i}",
                "kind": "demo",
                "status": "active",
                "tags": ["alpha", "beta"],
                "score": i * 3,
            }
            for i in range(1, 120)
        ]

        self.assertLess(toon_size_bytes(rows), json_size_bytes(rows))

    def test_toon_std_nested_blocks_and_nova_extensions(self) -> None:
        text = """@toon v1
@type std
root:
  |k|v|
  |v|0.1.6|
  |rt|.|
sum:
  |i|v|
  |0|project=nova|
  |1|routes=1|
cap:
  |i|v|
  |0|net|
  |1|html|
#nova_nd:
  |k|v|
  |sel|env:NOVA_NET_DRIVER|
  |nt|browser=headless,install_chromium,js|
"""
        value = decode_toon(text)
        self.assertEqual(value["v"], "0.1.6")
        self.assertEqual(value["rt"], ".")
        self.assertEqual(value["sum"], ["project=nova", "routes=1"])
        self.assertEqual(value["cap"], ["net", "html"])
        self.assertEqual(value["nd"]["sel"], "env:NOVA_NET_DRIVER")
        self.assertEqual(value["nd"]["nt"], "browser=headless,install_chromium,js")

    def test_parse_toon_uses_toon_decoder(self) -> None:
        payload = """@toon v1
@type std
root:
  |k|v|
  |v|0.1.6|
"""
        parsed = parse_toon(payload)
        self.assertEqual(parsed["v"], "0.1.6")

    def test_http_text_toon_request_and_response(self) -> None:
        server = run_server(DEMO_APP, host="127.0.0.1", port=0, capabilities={"db"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)

        host, port = server.server_address

        post_url = f"http://{host}:{port}/items.toon"
        post_body = encode_toon({"name": "toon-row"}).encode("utf-8")
        post_req = urllib.request.Request(
            post_url,
            data=post_body,
            method="POST",
            headers={"Content-Type": "text/toon"},
        )
        with urllib.request.urlopen(post_req, timeout=2) as res:
            self.assertEqual(res.status, 200)
            self.assertIn("text/toon", res.headers.get("Content-Type", ""))
            created = decode_toon(res.read().decode("utf-8"))
            self.assertEqual(created["name"], "toon-row")

        get_url = f"http://{host}:{port}/items.toon"
        with urllib.request.urlopen(get_url, timeout=2) as res:
            self.assertEqual(res.status, 200)
            self.assertIn("text/toon", res.headers.get("Content-Type", ""))
            rows = decode_toon(res.read().decode("utf-8"))
            self.assertTrue(isinstance(rows, list))
            self.assertGreaterEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], "toon-row")

        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
