import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

from nova.checker import check_ast
from nova.parser import parse_nova
from nova.runtime import NovaRuntime


class _LocalHtmlHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"<html><head><title>Local Demo</title></head><body><h1>Local</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class NovaExperimentalCapScrapingTests(unittest.TestCase):
    def test_html_tte_and_sct_with_dummy_html(self) -> None:
        source = '''
mdl scrape v"0.1.2" rst<any, err> {
  rte GET "/scrape" {
    cap [html]
    let pg = "<html><head><title>Demo</title></head><body><h1>A</h1><h1>B</h1></body></html>"
    let ti = cap html.tte(pg)
    let h1 = cap html.sct(pg, "h1")
    rst.ok({title: ti, h1: h1})
  }
}
'''
        runtime = NovaRuntime.from_source(source, capabilities={"html"})
        status, payload = runtime.dispatch("GET", "/scrape", {}, None)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["title"], "Demo")
        self.assertEqual(payload["data"]["h1"], ["A", "B"])

    def test_http_get_requires_net_cap(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHtmlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        time.sleep(0.05)
        host, port = server.server_address
        source = '''
mdl scrape v"0.1.2" rst<any, err> {
  rte GET "/scrape" {
    let pg = cap http.get("http://HOST:PORT/")
    rst.ok({len: pg})
  }
}
'''
        source = source.replace("HOST", str(host)).replace("PORT", str(port))
        runtime = NovaRuntime.from_source(source, capabilities=set())
        status, payload = runtime.dispatch("GET", "/scrape", {}, None)

        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "CAP_DECLARATION_REQUIRED")
        self.assertIn("declared via cap [net]", payload["error"]["msg"])

    def test_checker_accepts_experimental_cap_calls(self) -> None:
        source = '''
mdl scrape v"0.1.2" rst<any, err> {
  rte GET "/scrape" {
    let pg = "<html><head><title>Demo</title></head><body><h1>A</h1></body></html>"
    let ti = cap html.tte(pg)
    let h1 = cap html.sct(pg, "h1")
    rst.ok({title: ti, h1: h1})
  }
}
'''
        report = check_ast(parse_nova(source))
        self.assertTrue(report.ok)

    def test_checker_rejects_bad_cap_arity(self) -> None:
        source = '''
mdl scrape v"0.1.2" rst<any, err> {
  rte GET "/scrape" {
    let pg = "<html><body><h1>A</h1></body></html>"
    let h1 = cap html.sct(pg)
    rst.ok({h1: h1})
  }
}
'''
        report = check_ast(parse_nova(source))
        self.assertFalse(report.ok)
        rendered = "\n".join(f"[{d.code}] {d.path}: {d.message}" for d in report.diagnostics)
        self.assertIn("NVC332", rendered)


if __name__ == "__main__":
    unittest.main()
