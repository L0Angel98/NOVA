import unittest

from nova.checker import check_ast
from nova.parser import parse_nova


class NovaCheckerTests(unittest.TestCase):
    def test_checker_accepts_well_typed_program(self) -> None:
        source = '''
mdl api {
  fn status(flag: bool): rst<str, err> {
    if flag {
      rst.ok("ok")
    } els {
      err {code: "E_FAIL", msg: "fail"}
    }
  }

  rte "/health" GET json: rst<str, err> {
    let healthy: bool = tru
    let label: str = match healthy {
      tru => "up"
      fal => "down"
    }

    if healthy {
      rst.ok(label)
    } els {
      err {code: "E_DOWN", msg: "service down"}
    }
  }
}
'''

        ast = parse_nova(source)
        rst = check_ast(ast)
        self.assertTrue(rst.ok)
        self.assertEqual(rst.diagnostics, [])

    def test_checker_reports_non_exhaustive_and_route_type_errors(self) -> None:
        source = '''
rte "/x" GET json {
  let flag: bool = tru
  let x: str = match flag {
    tru => "ok"
  }

  if flag {
    rst.ok(x)
  }
}
'''

        rst = check_ast(parse_nova(source))
        codes = [d.code for d in rst.diagnostics]

        self.assertIn("NVC305", codes)  # route without explicit rst<T, E>
        self.assertIn("NVC211", codes)  # if without els
        self.assertIn("NVC224", codes)  # non-exhaustive bool match


if __name__ == "__main__":
    unittest.main()

