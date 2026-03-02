import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import unittest

from nova.runtime import NovaRuntime


class _HtmlHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"<html><head><title>NOVA</title></head><body><h1>Hello</h1><p>World</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class NovaCapabilitiesV013Tests(unittest.TestCase):
    def test_http_html_caps_work_with_short_keys(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HtmlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)

        host, port = server.server_address
        source = f'''
rte "/x" GET json: rst<any, err> {{
  cap [net, html]
  let pg = http.get("http://{host}:{port}/")
  let ti = html.tte(pg)
  let h1 = html.sct(pg, "h1")
  rst.ok({{st: pg.st, ti: ti, h1: h1}})
}}
'''
        runtime = NovaRuntime.from_source(source, capabilities={"net"})
        status, payload = runtime.dispatch("GET", "/x", {}, None)

        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["st"], 200)
        self.assertEqual(payload["data"]["ti"], "NOVA")
        self.assertEqual(payload["data"]["h1"], ["Hello"])

    def test_http_errors_are_structured(self) -> None:
        source = '''
rte "/x" GET json: rst<any, err> {
  cap [net]
  rst.ok(http.get("http://127.0.0.1:1", nul, num0.1))
}
'''
        runtime = NovaRuntime.from_source(source, capabilities={"net"})
        status, payload = runtime.dispatch("GET", "/x", {}, None)
        self.assertGreaterEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn(payload["error"]["code"], {"NET_REQ", "NET_INPUT"})

    def test_db_sqlite_cap_mvp(self) -> None:
        source = '''
rte "/db" GET json: rst<any, err> {
  cap [db]
  let h = db.opn("out/test_v013.db")
  db.qry(h, "create table if not exists usr (id integer primary key, nm text)")
  db.qry(h, "delete from usr")
  db.qry(h, "insert into usr (nm) values (?)", ["ada"])
  let rows = db.qry(h, "select id, nm from usr order by id asc")
  db.cls(h)
  rst.ok(rows)
}
'''
        runtime = NovaRuntime.from_source(source, capabilities={"db"})
        status, payload = runtime.dispatch("GET", "/db", {}, None)
        self.assertEqual(status, 200, json.dumps(payload))
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["data"][0]["nm"], "ada")


if __name__ == "__main__":
    unittest.main()
