import unittest

from nova.db_ir import build_ir_from_table_stmt, compile_plan
from nova.parser import parse_nova
from nova.runtime import NovaRuntime


class NovaDbIrTests(unittest.TestCase):
    def test_build_ir_for_tb_get(self) -> None:
        ast = parse_nova("tb users.get")
        stmt = ast["body"][0]

        ir = build_ir_from_table_stmt(stmt)
        self.assertEqual(ir.op, "get")
        self.assertEqual(ir.table_expr["type"], "Identifier")
        self.assertEqual(ir.table_expr["name"], "users")

        plan = compile_plan(
            ir,
            eval_table_name=lambda expr: expr["name"],
            eval_expr=lambda expr: expr,
        )
        self.assertEqual(plan.table, "users")
        self.assertEqual(plan.op, "get")

    def test_build_ir_for_tb_query_block(self) -> None:
        source = '''
fn q() {
  tb users.q {
    whe id == num7
    ord created_at desc
    lim num10
  }
}
'''
        ast = parse_nova(source)
        stmt = ast["body"][0]["body"][0]

        ir = build_ir_from_table_stmt(stmt)
        self.assertEqual(ir.op, "q")
        self.assertIsNotNone(ir.where_expr)
        self.assertIsNotNone(ir.order_field_expr)
        self.assertIsNotNone(ir.limit_expr)

        def eval_expr(expr):
            if expr["type"] == "NumberLiteral":
                return int(expr["value"])
            if expr["type"] == "Identifier":
                return expr["name"]
            return expr

        plan = compile_plan(
            ir,
            eval_table_name=lambda expr: expr["name"],
            eval_expr=eval_expr,
        )
        self.assertEqual(plan.table, "users")
        self.assertEqual(plan.op, "q")
        self.assertEqual(plan.limit, 10)
        self.assertEqual(plan.order_field, "created_at")
        self.assertEqual(plan.order_direction, "desc")

    def test_runtime_executes_tb_get_and_tb_q(self) -> None:
        source = '''
rte "/users" POST json: rst<any, err> {
  cap [db]
  tb users
  if body == nul {
    err {code: "BAD_REQUEST", msg: "body required"}
  } els {
    rst.ok(db.create(body))
  }
}

rte "/users" GET json: rst<any, err> {
  cap [db]
  tb users.get
}

rte "/users/top" GET json: rst<any, err> {
  cap [db]
  tb users.q {
    ord id desc
    lim num1
  }
}
'''
        runtime = NovaRuntime.from_source(source, capabilities={"db"})

        status, payload = runtime.dispatch("POST", "/users", {}, {"name": "a"})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

        status, payload = runtime.dispatch("POST", "/users", {}, {"name": "b"})
        self.assertEqual(status, 200)

        status, payload = runtime.dispatch("GET", "/users", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["data"]), 2)

        status, payload = runtime.dispatch("GET", "/users/top", {}, None)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["data"][0]["name"], "b")


if __name__ == "__main__":
    unittest.main()

