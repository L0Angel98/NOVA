import unittest

from nova.runtime import NovaRuntime, RuntimeBuildError


class NovaCapEnforcementTests(unittest.TestCase):
    def test_db_cap_is_inferred_from_tb(self) -> None:
        source = '''
rte "/x" GET json: rst<any, err> {
  tb users.get
}
'''
        runtime = NovaRuntime.from_source(source, capabilities={"db"})
        status, payload = runtime.dispatch("GET", "/x", {}, None)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_db_route_blocked_when_runtime_cap_missing(self) -> None:
        source = '''
rte "/x" GET json: rst<any, err> {
  cap [db]
  tb users.get
}
'''
        runtime = NovaRuntime.from_source(source, capabilities=set())
        status, payload = runtime.dispatch("GET", "/x", {}, None)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "CAP_FORBIDDEN")

    def test_cap_must_be_top_level_and_static(self) -> None:
        nested = '''
rte "/x" GET json: rst<any, err> {
  if tru {
    cap [db]
  } els {
    rst.ok("x")
  }
}
'''
        dynamic = '''
rte "/x" GET json: rst<any, err> {
  let p = "db"
  cap [p]
  rst.ok("x")
}
'''
        with self.assertRaises(RuntimeBuildError):
            NovaRuntime.from_source(nested, capabilities={"db"})
        with self.assertRaises(RuntimeBuildError):
            NovaRuntime.from_source(dynamic, capabilities={"db"})

    def test_env_fs_net_are_enforced(self) -> None:
        source = '''
rte "/env" GET json: rst<any, err> {
  cap [env]
  rst.ok(env.keys())
}

rte "/fs" GET json: rst<any, err> {
  cap [fs]
  rst.ok(fs.exists("NOT_REAL"))
}

rte "/net" GET json: rst<any, err> {
  cap [net]
  rst.ok(net.get("http://example.com", num0.1))
}
'''
        runtime = NovaRuntime.from_source(source, capabilities={"env"})

        status, payload = runtime.dispatch("GET", "/env", {}, None)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

        status, payload = runtime.dispatch("GET", "/fs", {}, None)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "CAP_FORBIDDEN")

        status, payload = runtime.dispatch("GET", "/net", {}, None)
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "CAP_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()

