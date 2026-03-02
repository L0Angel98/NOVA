import unittest

from nova.formatter import format_nova
from nova.parser import parse_nova


class NovaRoundtripTests(unittest.TestCase):
    def test_roundtrip_ast_is_identical(self) -> None:
        source = '''
module api {
  import "core/net"

  public function list_users(ctx) {
    let task = async {
      table users
      where active == true
      order created_at descending
      limit 010
    }

    let rows = await task

    let state = match rows {
      null => "empty",
      _ => "ok"
    }

    if state == "ok" {
      capability ["users.write", "users.read"]
      route "/users" "GET" json {
        cap ["users.read", "users.write"]
        tb users
        whe active == tru
        ord created_at desc
        lim num20
      }
    } else {
      error {msg: "no_rows", code: "E_EMPTY"}
    }
  }
}
'''

        ast1 = parse_nova(source)
        formatted = format_nova(ast1)
        ast2 = parse_nova(formatted)

        self.assertEqual(ast1, ast2)

    def test_formatter_normalizes_aliases_literals_and_order(self) -> None:
        source = '''
module test {
  public function x() {
    let n = 0007
    let s = "hola"
    capability ["z", "a"]
    error {b: 2, a: 1}
    if true {
      order created_at descending
    } else {
      limit 0010
    }
  }
}
'''

        formatted = format_nova(parse_nova(source))

        self.assertIn("mdl test", formatted)
        self.assertIn("pub fn x()", formatted)
        self.assertIn("let n = num7", formatted)
        self.assertIn('let s = "hola"', formatted)
        self.assertIn('cap ["a", "z"]', formatted)
        self.assertIn('err {a: num1, b: num2}', formatted)
        self.assertNotIn("ord created_at asc", formatted)
        self.assertIn("ord created_at desc", formatted)
        self.assertIn("lim num10", formatted)

        self.assertNotIn("module", formatted)
        self.assertNotIn("function", formatted)
        self.assertNotIn("capability", formatted)
        self.assertNotIn("error", formatted)
        self.assertNotIn("else", formatted)

    def test_typed_ast_shape(self) -> None:
        source = 'fn ping() { let ok = tru }'
        ast = parse_nova(source)

        self.assertEqual(ast["type"], "Program")
        self.assertEqual(ast["body"][0]["type"], "FunctionDecl")
        let_stmt = ast["body"][0]["body"][0]
        self.assertEqual(let_stmt["type"], "LetStmt")
        self.assertEqual(let_stmt["value"]["type"], "BooleanLiteral")

    def test_roundtrip_with_type_annotations(self) -> None:
        source = '''
fn typed(a: num, b: Option<str>): rst<str, err> {
  let x: num = a + num1
  if tru {
    rst.ok(str"ok")
  } els {
    err {code: str"E", msg: str"bad"}
  }
}
'''
        ast1 = parse_nova(source)
        ast2 = parse_nova(format_nova(ast1))
        self.assertEqual(ast1, ast2)

    def test_roundtrip_db_ir_tb_query_forms(self) -> None:
        source = '''
fn q() {
  tb users.get
  tb users.q {
    whe id == num1
    ord created_at desc
    lim num10
  }
}
'''
        ast1 = parse_nova(source)
        formatted = format_nova(ast1)
        ast2 = parse_nova(formatted)
        self.assertEqual(ast1, ast2)
        self.assertIn("tb users.get", formatted)
        self.assertIn("tb users.q {", formatted)


if __name__ == "__main__":
    unittest.main()

