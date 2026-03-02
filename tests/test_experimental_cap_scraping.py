import unittest

from nova.checker import check_ast
from nova.parser import parse_nova
from nova.runtime import NovaRuntime


class NovaExperimentalCapScrapingTests(unittest.TestCase):
    def test_html_tte_and_sct_with_dummy_html(self) -> None:
        source = '''
mdl scrape v"0.1.2" rst<any, err> {
  rte GET "/scrape" {
    let pg = "<html><head><title>Demo</title></head><body><h1>A</h1><h1>B</h1></body></html>"
    let ti = cap html.tte(pg)
    let h1 = cap html.sct(pg, "h1")
    rst.ok({title: ti, h1: h1})
  }
}
'''
        runtime = NovaRuntime.from_source(source, capabilities=set())
        status, payload = runtime.dispatch("GET", "/scrape", {}, None)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"]["title"], "Demo")
        self.assertEqual(payload["data"]["h1"], ["A", "B"])

    def test_http_get_requires_net_cap(self) -> None:
        source = '''
mdl scrape v"0.1.2" rst<any, err> {
  rte GET "/scrape" {
    let pg = cap http.get("https://example.com")
    rst.ok({len: pg})
  }
}
'''
        runtime = NovaRuntime.from_source(source, capabilities=set())
        status, payload = runtime.dispatch("GET", "/scrape", {}, None)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "CAP_FORBIDDEN")
        self.assertIn("NVR200", payload["error"]["msg"])

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
