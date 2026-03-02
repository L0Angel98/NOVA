from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class NovaType:
    kind: str
    args: Tuple["NovaType", ...] = ()
    fields: Tuple[Tuple[str, "NovaType"], ...] = ()


TYPE_STR = NovaType("str")
TYPE_NUM = NovaType("num")
TYPE_BOOL = NovaType("bool")
TYPE_NUL = NovaType("nul")
TYPE_MDL = NovaType("mdl")
TYPE_ERR = NovaType("err")
TYPE_VOID = NovaType("void")
TYPE_UNKNOWN = NovaType("unknown")
TYPE_ANY = NovaType("any")


def t_option(inner: NovaType) -> NovaType:
    return NovaType("Option", (inner,))


def t_result(ok_type: NovaType, err_type: NovaType) -> NovaType:
    return NovaType("rst", (ok_type, err_type))


def t_array(inner: NovaType) -> NovaType:
    return NovaType("array", (inner,))


def t_fn(params: List[NovaType], ret: NovaType) -> NovaType:
    return NovaType("fn", tuple(params + [ret]))


def t_async(inner: NovaType) -> NovaType:
    return NovaType("async", (inner,))


def t_object(fields: Dict[str, NovaType]) -> NovaType:
    return NovaType("object", fields=tuple(sorted(fields.items(), key=lambda item: item[0])))


def type_to_string(tp: NovaType) -> str:
    if tp.kind in {"str", "num", "bool", "nul", "mdl", "err", "void", "unknown", "any"}:
        return tp.kind
    if tp.kind == "Option":
        return f"Option<{type_to_string(tp.args[0])}>"
    if tp.kind == "rst":
        return f"rst<{type_to_string(tp.args[0])}, {type_to_string(tp.args[1])}>"
    if tp.kind == "array":
        return f"[{type_to_string(tp.args[0])}]"
    if tp.kind == "async":
        return f"asy<{type_to_string(tp.args[0])}>"
    if tp.kind == "object":
        return "{" + ", ".join(f"{k}: {type_to_string(v)}" for k, v in tp.fields) + "}"
    if tp.kind == "fn":
        params = ", ".join(type_to_string(item) for item in tp.args[:-1])
        return f"fn({params}) -> {type_to_string(tp.args[-1])}"
    if tp.kind.startswith("named:"):
        return tp.kind.removeprefix("named:")
    return tp.kind


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str


@dataclass
class CheckReport:
    diagnostics: List[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.diagnostics


class Env:
    def __init__(self, parent: Optional["Env"] = None) -> None:
        self.parent = parent
        self.symbols: Dict[str, NovaType] = {}

    def define(self, name: str, tp: NovaType) -> bool:
        if name in self.symbols:
            return False
        self.symbols[name] = tp
        return True

    def lookup(self, name: str) -> Optional[NovaType]:
        cur: Optional[Env] = self
        while cur is not None:
            if name in cur.symbols:
                return cur.symbols[name]
            cur = cur.parent
        return None


class Checker:
    def __init__(self) -> None:
        self._diagnostics: List[Diagnostic] = []
        self._module_result_stack: List[NovaType] = []

    def check(self, ast: Dict[str, Any]) -> CheckReport:
        self._module_result_stack = []
        if ast.get("type") != "Program":
            self._error("NVC000", "Program", "AST root must be Program")
            return CheckReport(self._sorted_diagnostics())

        env = Env()
        env.define("json", NovaType("format:json"))
        env.define("toon", NovaType("format:toon"))
        env.define("Option", NovaType("meta:Option"))
        env.define("rst", NovaType("meta:rst"))

        body = ast.get("body", [])
        self._check_block(body, env, "Program.body")
        return CheckReport(self._sorted_diagnostics())

    def _predeclare_block(self, body: List[Dict[str, Any]], env: Env, path: str) -> None:
        for idx, stmt in enumerate(body):
            stmt_path = f"{path}[{idx}]"
            target = self._unwrap_public(stmt)
            typ = target["type"]
            if typ == "ModuleDecl":
                if not env.define(target["name"], TYPE_MDL):
                    self._error("NVC101", stmt_path, f"Redeclaration of symbol '{target['name']}'")
            if typ == "FunctionDecl":
                fn_type = self._function_type_from_decl(target, f"{stmt_path}.declaration")
                if not env.define(target["name"], fn_type):
                    self._error("NVC101", stmt_path, f"Redeclaration of symbol '{target['name']}'")

    def _check_block(self, body: List[Dict[str, Any]], env: Env, path: str) -> NovaType:
        self._predeclare_block(body, env, path)
        terminal_type = TYPE_VOID
        for idx, stmt in enumerate(body):
            stmt_path = f"{path}[{idx}]"
            stmt_type = self._check_statement(stmt, env, stmt_path)
            if stmt_type.kind != "void":
                terminal_type = stmt_type
        return terminal_type

    def _check_statement(self, stmt: Dict[str, Any], env: Env, path: str) -> NovaType:
        typ = stmt["type"]

        if typ == "PublicDecl":
            return self._check_statement(stmt["declaration"], env, f"{path}.declaration")

        if typ == "ModuleDecl":
            if stmt.get("version") is not None and not isinstance(stmt.get("version"), str):
                self._error("NVC104", f"{path}.version", "module version must be string literal")

            module_default = TYPE_UNKNOWN
            if stmt.get("default_result_type") is not None:
                module_default = self._resolve_type_ref(
                    stmt.get("default_result_type"),
                    f"{path}.default_result_type",
                )
                if module_default.kind not in {"unknown", "rst"}:
                    self._error(
                        "NVC306",
                        f"{path}.default_result_type",
                        "module default result type must be rst<T, E>",
                    )

            module_env = Env(env)
            self._module_result_stack.append(module_default)
            try:
                self._check_block(stmt.get("body", []), module_env, f"{path}.body")
            finally:
                self._module_result_stack.pop()
            return TYPE_VOID

        if typ == "ImportStmt":
            source_type = self._check_expr(stmt["source"], env, f"{path}.source")
            self._expect_assignable(source_type, TYPE_STR, "NVC201", f"{path}.source", "import source must be str")
            return TYPE_VOID

        if typ == "FunctionDecl":
            fn_type = env.lookup(stmt["name"])
            if fn_type is None:
                fn_type = self._function_type_from_decl(stmt, path)
                env.define(stmt["name"], fn_type)

            fn_env = Env(env)
            params = stmt.get("params", [])
            for pidx, param in enumerate(params):
                if isinstance(param, str):
                    pname = param
                    ptype = TYPE_UNKNOWN
                else:
                    pname = param["name"]
                    ptype = self._resolve_type_ref(param.get("annotation"), f"{path}.params[{pidx}].annotation")
                if not fn_env.define(pname, ptype):
                    self._error("NVC101", f"{path}.params[{pidx}]", f"Duplicate parameter '{pname}'")

            body_type = self._check_block(stmt.get("body", []), fn_env, f"{path}.body")
            declared_ret = fn_type.args[-1] if fn_type.kind == "fn" and fn_type.args else TYPE_UNKNOWN
            if declared_ret.kind != "unknown" and body_type.kind != "void":
                self._expect_assignable(
                    body_type,
                    declared_ret,
                    "NVC240",
                    f"{path}.body",
                    f"Function body type {type_to_string(body_type)} is not assignable to declared return {type_to_string(declared_ret)}",
                )
            return TYPE_VOID

        if typ == "LetStmt":
            annotation = self._resolve_type_ref(stmt.get("annotation"), f"{path}.annotation")
            value_type = self._check_expr(stmt["value"], env, f"{path}.value")
            final_type = value_type
            if stmt.get("annotation") is not None:
                self._expect_assignable(
                    value_type,
                    annotation,
                    "NVC202",
                    path,
                    f"let '{stmt['name']}' expects {type_to_string(annotation)} but got {type_to_string(value_type)}",
                )
                final_type = annotation
            if not env.define(stmt["name"], final_type):
                self._error("NVC101", path, f"Redeclaration of symbol '{stmt['name']}'")
            return TYPE_VOID

        if typ == "IfStmt":
            cond_type = self._check_expr(stmt["condition"], env, f"{path}.condition")
            self._expect_assignable(cond_type, TYPE_BOOL, "NVC210", f"{path}.condition", "if condition must be bool")
            then_type = self._check_block(stmt.get("then", []), Env(env), f"{path}.then")
            else_branch = stmt.get("else")
            if else_branch is None:
                self._error("NVC211", path, "if must include els for exhaustiveness in v0.1")
                return TYPE_VOID
            if else_branch["type"] == "ElseIf":
                else_type = self._check_statement(else_branch["branch"], Env(env), f"{path}.else.branch")
            elif else_branch["type"] == "ElseBlock":
                else_type = self._check_block(else_branch.get("body", []), Env(env), f"{path}.else.body")
            else:
                self._error("NVC212", f"{path}.else", f"Unsupported else branch kind {else_branch['type']}")
                else_type = TYPE_UNKNOWN
            return self._merge_branch_types(then_type, else_type, path)

        if typ == "GuardStmt":
            targets = stmt.get("targets", [])
            if not targets:
                self._error("NVC213", path, "grd requires at least one target expression")
            for idx, expr in enumerate(targets):
                self._check_expr(expr, env, f"{path}.targets[{idx}]")
            code_type = self._check_expr(stmt["code"], env, f"{path}.code")
            self._expect_assignable(code_type, TYPE_STR, "NVC214", f"{path}.code", "grd code must be str")
            return TYPE_VOID

        if typ == "RouteDecl":
            path_type = self._check_expr(stmt["path"], env, f"{path}.path")
            self._expect_assignable(path_type, TYPE_STR, "NVC301", f"{path}.path", "rte path must be str")

            method_expr = stmt["method"]
            method_name = self._extract_route_method_name(method_expr, env, f"{path}.method")
            if method_name is not None:
                aliases = {"DEL": "DELETE", "PAT": "PATCH", "OPT": "OPTIONS", "HED": "HEAD"}
                method_name = aliases.get(method_name, method_name)
                allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"}
                if method_name not in allowed:
                    self._error("NVC303", f"{path}.method", f"Unsupported method '{method_name}'")

            if not self._is_valid_route_format(stmt["format"]):
                self._error("NVC304", f"{path}.format", "rte format must be json or toon")

            if stmt.get("result_type") is None:
                declared_result = self._current_module_result_type()
                if declared_result.kind == "unknown":
                    self._error("NVC305", path, "rte must declare result type (rst<T, E>) or inherit module default")
            else:
                declared_result = self._resolve_type_ref(stmt.get("result_type"), f"{path}.result_type")
            if declared_result.kind not in {"unknown", "rst"}:
                self._error("NVC306", f"{path}.result_type", "rte result type must be rst<T, E>")

            route_body_type = self._check_block(stmt.get("body", []), Env(env), f"{path}.body")
            if route_body_type.kind == "void":
                self._error("NVC307", f"{path}.body", "rte body must end with a typed value (typically rst<T, E> or err)")
            elif declared_result.kind != "unknown":
                self._expect_assignable(
                    route_body_type,
                    declared_result,
                    "NVC308",
                    f"{path}.body",
                    f"rte body type {type_to_string(route_body_type)} is not assignable to {type_to_string(declared_result)}",
                )
            return TYPE_VOID

        if typ == "TableStmt":
            self._check_expr(stmt["table"], env, f"{path}.table", allow_unresolved_ident=True)
            op = stmt.get("op")
            if op not in {None, "get", "q"}:
                self._error("NVC323", f"{path}.op", f"tb op must be get or q, got '{op}'")

            for idx, clause in enumerate(stmt.get("query", [])):
                ctype = clause.get("type")
                clause_path = f"{path}.query[{idx}]"
                if ctype not in {"WhereStmt", "LimitStmt", "OrderStmt"}:
                    self._error("NVC324", clause_path, "tb query block only allows whe/lim/ord")
                    continue
                self._check_statement(clause, env, clause_path)

            if op == "get" or (op == "q" and bool(stmt.get("query"))):
                # Declarative tb shortcuts can materialize rows in runtime.
                return TYPE_UNKNOWN
            return TYPE_VOID

        if typ == "WhereStmt":
            cond = self._check_expr(stmt["condition"], env, f"{path}.condition", allow_unresolved_ident=True)
            if cond.kind not in {"bool", "unknown"}:
                self._error("NVC320", f"{path}.condition", "whe condition should be bool")
            return TYPE_VOID

        if typ == "LimitStmt":
            value_type = self._check_expr(stmt["value"], env, f"{path}.value")
            self._expect_assignable(value_type, TYPE_NUM, "NVC321", f"{path}.value", "lim expects num")
            return TYPE_VOID

        if typ == "OrderStmt":
            self._check_expr(stmt["field"], env, f"{path}.field", allow_unresolved_ident=True)
            direction = stmt["direction"]
            if direction["type"] == "Identifier":
                if direction["name"] not in {"asc", "desc"}:
                    self._error("NVC322", f"{path}.direction", "ord direction must be asc or desc")
            elif direction["type"] == "StringLiteral":
                if direction["value"] not in {"asc", "desc"}:
                    self._error("NVC322", f"{path}.direction", "ord direction must be asc or desc")
            else:
                self._check_expr(direction, env, f"{path}.direction")
                self._error("NVC322", f"{path}.direction", "ord direction must be asc or desc")
            return TYPE_VOID

        if typ == "ErrorStmt":
            value_type = self._check_expr(stmt["value"], env, f"{path}.value")
            self._validate_err_payload(value_type, f"{path}.value")
            return t_result(TYPE_UNKNOWN, TYPE_ERR)

        if typ == "CapStmt":
            value_type = self._check_expr(stmt["value"], env, f"{path}.value")
            if value_type.kind == "array":
                self._expect_assignable(value_type.args[0], TYPE_STR, "NVC330", f"{path}.value", "cap entries must be str")
            else:
                self._error("NVC330", f"{path}.value", "cap expects array of str")
            return TYPE_VOID

        if typ == "ExprStmt":
            return self._check_expr(stmt["expression"], env, f"{path}.expression")

        self._error("NVC001", path, f"Unsupported statement type '{typ}'")
        return TYPE_UNKNOWN

    def _check_expr(self, expr: Dict[str, Any], env: Env, path: str, allow_unresolved_ident: bool = False) -> NovaType:
        typ = expr["type"]
        if typ == "StringLiteral":
            return TYPE_STR
        if typ == "NumberLiteral":
            return TYPE_NUM
        if typ == "BooleanLiteral":
            return TYPE_BOOL
        if typ == "NullLiteral":
            return TYPE_NUL
        if typ == "Identifier":
            name = expr["name"]
            symbol_type = env.lookup(name)
            if symbol_type is not None:
                return symbol_type
            if allow_unresolved_ident:
                return TYPE_UNKNOWN
            self._error("NVC110", path, f"Undefined identifier '{name}'")
            return TYPE_UNKNOWN
        if typ == "ArrayLiteral":
            item_types = [self._check_expr(item, env, f"{path}.items[{idx}]", allow_unresolved_ident) for idx, item in enumerate(expr.get("items", []))]
            if not item_types:
                return t_array(TYPE_UNKNOWN)
            merged = item_types[0]
            for idx, item_type in enumerate(item_types[1:], start=1):
                merged = self._merge_expr_types(merged, item_type, f"{path}.items[{idx}]")
            return t_array(merged)
        if typ == "ObjectLiteral":
            fields: Dict[str, NovaType] = {}
            for idx, field in enumerate(expr.get("fields", [])):
                fields[field["key"]] = self._check_expr(field["value"], env, f"{path}.fields[{idx}].value", allow_unresolved_ident)
            return t_object(fields)
        if typ == "MemberExpr":
            owner = self._check_expr(expr["object"], env, f"{path}.object", allow_unresolved_ident)
            if owner.kind.startswith("named:"):
                return TYPE_UNKNOWN
            if owner.kind == "meta:Option" and expr["property"] in {"some", "none"}:
                return TYPE_UNKNOWN
            if owner.kind == "meta:rst" and expr["property"] in {"ok", "err"}:
                return TYPE_UNKNOWN
            return TYPE_UNKNOWN
        if typ == "CapExpr":
            return self._check_cap_expr(expr, env, path, allow_unresolved_ident)
        if typ == "CallExpr":
            return self._check_call_expr(expr, env, path, allow_unresolved_ident)
        if typ == "UnaryExpr":
            inner = self._check_expr(expr["expression"], env, f"{path}.expression", allow_unresolved_ident)
            op = expr["operator"]
            if op == "-":
                self._expect_assignable(inner, TYPE_NUM, "NVC120", path, "Unary '-' expects num")
                return TYPE_NUM
            if op == "!":
                self._expect_assignable(inner, TYPE_BOOL, "NVC121", path, "Unary '!' expects bool")
                return TYPE_BOOL
            self._error("NVC122", path, f"Unsupported unary operator '{op}'")
            return TYPE_UNKNOWN
        if typ == "AwaitExpr":
            awaited = self._check_expr(expr["expression"], env, f"{path}.expression", allow_unresolved_ident)
            if awaited.kind == "async":
                return awaited.args[0]
            self._error("NVC130", path, "awt expects asy<T>")
            return TYPE_UNKNOWN
        if typ == "CapExpr":
            return self._check_expr(expr["expression"], env, f"{path}.expression", allow_unresolved_ident)
        if typ == "AsyncExpr":
            block_type = self._check_block(expr.get("body", []), Env(env), f"{path}.body")
            if block_type.kind == "void":
                block_type = TYPE_UNKNOWN
            return t_async(block_type)
        if typ == "BinaryExpr":
            return self._check_binary_expr(expr, env, path, allow_unresolved_ident)
        if typ == "MatchExpr":
            return self._check_match_expr(expr, env, path, allow_unresolved_ident)
        self._error("NVC002", path, f"Unsupported expression type '{typ}'")
        return TYPE_UNKNOWN

    def _check_call_expr(self, expr: Dict[str, Any], env: Env, path: str, allow_unresolved_ident: bool) -> NovaType:
        callee = expr["callee"]
        args = expr.get("args", [])

        if callee["type"] == "MemberExpr" and callee["object"]["type"] == "Identifier":
            owner = callee["object"]["name"]
            prop = callee["property"]
            if owner == "Option":
                if prop == "some":
                    if len(args) != 1:
                        self._error("NVC140", path, "Option.some expects 1 argument")
                        return t_option(TYPE_UNKNOWN)
                    inner = self._check_expr(args[0], env, f"{path}.args[0]", allow_unresolved_ident)
                    return t_option(inner)
                if prop == "none":
                    if len(args) != 0:
                        self._error("NVC140", path, "Option.none expects 0 arguments")
                    return t_option(TYPE_UNKNOWN)
            if owner == "rst":
                if prop == "ok":
                    if len(args) != 1:
                        self._error("NVC141", path, "rst.ok expects 1 argument")
                        return t_result(TYPE_UNKNOWN, TYPE_ERR)
                    ok_type = self._check_expr(args[0], env, f"{path}.args[0]", allow_unresolved_ident)
                    return t_result(ok_type, TYPE_ERR)
                if prop == "err":
                    if len(args) != 1:
                        self._error("NVC141", path, "rst.err expects 1 argument")
                        return t_result(TYPE_UNKNOWN, TYPE_ERR)
                    err_type = self._check_expr(args[0], env, f"{path}.args[0]", allow_unresolved_ident)
                    return t_result(TYPE_UNKNOWN, err_type)

        callee_type = self._check_expr(callee, env, f"{path}.callee", allow_unresolved_ident)
        if callee_type.kind != "fn":
            self._error("NVC142", path, "Call target is not a function")
            for idx, arg in enumerate(args):
                self._check_expr(arg, env, f"{path}.args[{idx}]", allow_unresolved_ident)
            return TYPE_UNKNOWN

        param_types = list(callee_type.args[:-1])
        return_type = callee_type.args[-1]
        if len(param_types) != len(args):
            self._error("NVC143", path, f"Function expects {len(param_types)} args but got {len(args)}")
        for idx, arg in enumerate(args):
            arg_type = self._check_expr(arg, env, f"{path}.args[{idx}]", allow_unresolved_ident)
            if idx < len(param_types):
                self._expect_assignable(
                    arg_type,
                    param_types[idx],
                    "NVC144",
                    f"{path}.args[{idx}]",
                    f"Argument type {type_to_string(arg_type)} is not assignable to parameter {type_to_string(param_types[idx])}",
                )
        return return_type

    def _check_cap_expr(self, expr: Dict[str, Any], env: Env, path: str, allow_unresolved_ident: bool) -> NovaType:
        inner = expr.get("expression")
        if not isinstance(inner, dict):
            self._error("NVC331", path, "cap expects namespace operation call (e.g., cap http.get(...))")
            return TYPE_UNKNOWN

        if inner.get("type") != "CallExpr":
            self._error("NVC331", path, "cap expects call expression (e.g., cap http.get(...))")
            self._check_expr(inner, env, f"{path}.expression", allow_unresolved_ident)
            return TYPE_UNKNOWN

        callee = inner.get("callee", {})
        if (
            callee.get("type") != "MemberExpr"
            or callee.get("object", {}).get("type") != "Identifier"
        ):
            self._error("NVC331", path, "cap expects namespace operation call (ns.op(...))")
            for idx, arg in enumerate(inner.get("args", [])):
                self._check_expr(arg, env, f"{path}.expression.args[{idx}]", allow_unresolved_ident)
            return TYPE_UNKNOWN

        owner = callee["object"]["name"]
        op = callee["property"]
        args = inner.get("args", [])

        if owner == "http" and op == "get":
            if len(args) < 1 or len(args) > 3:
                self._error("NVC332", path, "cap http.get expects 1 to 3 args (url, h?, t?)")
            if len(args) >= 1:
                url_type = self._check_expr(args[0], env, f"{path}.expression.args[0]", allow_unresolved_ident)
                self._expect_assignable(url_type, TYPE_STR, "NVC333", f"{path}.expression.args[0]", "http.get url must be str")
            if len(args) >= 2:
                self._check_expr(args[1], env, f"{path}.expression.args[1]", allow_unresolved_ident)
            if len(args) >= 3:
                timeout_type = self._check_expr(args[2], env, f"{path}.expression.args[2]", allow_unresolved_ident)
                self._expect_assignable(timeout_type, TYPE_NUM, "NVC334", f"{path}.expression.args[2]", "http.get t must be num")
            return TYPE_STR

        if owner == "html" and op == "tte":
            if len(args) != 1:
                self._error("NVC332", path, "cap html.tte expects exactly 1 arg (html)")
            if len(args) >= 1:
                html_type = self._check_expr(args[0], env, f"{path}.expression.args[0]", allow_unresolved_ident)
                self._expect_assignable(html_type, TYPE_STR, "NVC333", f"{path}.expression.args[0]", "html.tte html must be str")
            return TYPE_STR

        if owner == "html" and op == "sct":
            if len(args) != 2:
                self._error("NVC332", path, "cap html.sct expects exactly 2 args (html, css)")
            if len(args) >= 1:
                html_type = self._check_expr(args[0], env, f"{path}.expression.args[0]", allow_unresolved_ident)
                self._expect_assignable(html_type, TYPE_STR, "NVC333", f"{path}.expression.args[0]", "html.sct html must be str")
            if len(args) >= 2:
                css_type = self._check_expr(args[1], env, f"{path}.expression.args[1]", allow_unresolved_ident)
                self._expect_assignable(css_type, TYPE_STR, "NVC333", f"{path}.expression.args[1]", "html.sct css must be str")
            return t_array(TYPE_STR)

        self._error("NVC335", path, f"unsupported cap operation '{owner}.{op}'")
        for idx, arg in enumerate(args):
            self._check_expr(arg, env, f"{path}.expression.args[{idx}]", allow_unresolved_ident)
        return TYPE_UNKNOWN

    def _check_binary_expr(self, expr: Dict[str, Any], env: Env, path: str, allow_unresolved_ident: bool) -> NovaType:
        left = self._check_expr(expr["left"], env, f"{path}.left", allow_unresolved_ident)
        right = self._check_expr(expr["right"], env, f"{path}.right", allow_unresolved_ident)
        op = expr["operator"]
        if op in {"+", "-", "*", "/"}:
            self._expect_assignable(left, TYPE_NUM, "NVC150", f"{path}.left", f"Operator '{op}' expects num")
            self._expect_assignable(right, TYPE_NUM, "NVC150", f"{path}.right", f"Operator '{op}' expects num")
            return TYPE_NUM
        if op in {"<", "<=", ">", ">="}:
            self._expect_assignable(left, TYPE_NUM, "NVC151", f"{path}.left", f"Operator '{op}' expects num")
            self._expect_assignable(right, TYPE_NUM, "NVC151", f"{path}.right", f"Operator '{op}' expects num")
            return TYPE_BOOL
        if op in {"&&", "||"}:
            self._expect_assignable(left, TYPE_BOOL, "NVC152", f"{path}.left", f"Operator '{op}' expects bool")
            self._expect_assignable(right, TYPE_BOOL, "NVC152", f"{path}.right", f"Operator '{op}' expects bool")
            return TYPE_BOOL
        if op in {"==", "!="}:
            if not self._is_comparable(left, right):
                self._error("NVC153", path, f"Cannot compare {type_to_string(left)} and {type_to_string(right)} with '{op}'")
            return TYPE_BOOL
        self._error("NVC154", path, f"Unsupported binary operator '{op}'")
        return TYPE_UNKNOWN

    def _check_match_expr(self, expr: Dict[str, Any], env: Env, path: str, allow_unresolved_ident: bool) -> NovaType:
        subject_type = self._check_expr(expr["subject"], env, f"{path}.subject", allow_unresolved_ident)
        cases = expr.get("cases", [])
        if not cases:
            self._error("NVC220", path, "match must declare at least one case")
            return TYPE_UNKNOWN
        value_types: List[NovaType] = []
        for idx, case in enumerate(cases):
            case_path = f"{path}.cases[{idx}]"
            self._check_match_pattern(case["pattern"], subject_type, f"{case_path}.pattern")
            value_types.append(self._check_expr(case["value"], env, f"{case_path}.value", allow_unresolved_ident))
        self._check_match_exhaustiveness(subject_type, cases, path)
        merged = value_types[0]
        for idx, value_type in enumerate(value_types[1:], start=1):
            merged = self._merge_expr_types(merged, value_type, f"{path}.cases[{idx}].value")
        return merged

    def _check_match_pattern(self, pattern: Dict[str, Any], subject_type: NovaType, path: str) -> None:
        typ = pattern["type"]
        if typ in {"WildcardPattern", "IdentifierPattern"}:
            return
        if typ == "LiteralPattern":
            lit_type = self._literal_type_from_node(pattern["value"])
            if subject_type.kind == "Option" and lit_type.kind != "nul":
                if not self._is_assignable(lit_type, subject_type.args[0]):
                    self._error("NVC221", path, f"Pattern literal {type_to_string(lit_type)} incompatible with {type_to_string(subject_type)}")
                return
            if not self._is_assignable(lit_type, subject_type) and subject_type.kind != "unknown":
                self._error("NVC221", path, f"Pattern literal {type_to_string(lit_type)} incompatible with {type_to_string(subject_type)}")
            return
        if typ == "ExprPattern":
            lit_type = self._check_expr(pattern["value"], Env(), f"{path}.value", allow_unresolved_ident=True)
            if not self._is_assignable(lit_type, subject_type) and subject_type.kind != "unknown":
                self._error("NVC222", path, f"Pattern expression {type_to_string(lit_type)} incompatible with {type_to_string(subject_type)}")
            return
        self._error("NVC223", path, f"Unsupported pattern type '{typ}'")

    def _check_match_exhaustiveness(self, subject_type: NovaType, cases: List[Dict[str, Any]], path: str) -> None:
        has_catch_all = any(case["pattern"]["type"] in {"WildcardPattern", "IdentifierPattern"} for case in cases)
        if has_catch_all:
            return
        if subject_type.kind == "bool":
            has_true = False
            has_false = False
            for case in cases:
                pattern = case["pattern"]
                if pattern["type"] == "LiteralPattern" and pattern["value"]["type"] == "BooleanLiteral":
                    has_true = has_true or bool(pattern["value"]["value"])
                    has_false = has_false or (not bool(pattern["value"]["value"]))
            if not (has_true and has_false):
                self._error("NVC224", path, "Non-exhaustive match for bool: requires tru and fal (or _)")
            return
        if subject_type.kind == "Option":
            inner = subject_type.args[0]
            has_null = False
            has_true = False
            has_false = False
            for case in cases:
                pattern = case["pattern"]
                if pattern["type"] != "LiteralPattern":
                    continue
                node = pattern["value"]
                if node["type"] == "NullLiteral":
                    has_null = True
                if node["type"] == "BooleanLiteral":
                    has_true = has_true or bool(node["value"])
                    has_false = has_false or (not bool(node["value"]))
            if inner.kind == "bool":
                if not (has_null and has_true and has_false):
                    self._error("NVC225", path, "Non-exhaustive match for Option<bool>: requires nul, tru, fal (or _)")
                return
            if inner.kind == "nul":
                if not has_null:
                    self._error("NVC225", path, "Non-exhaustive match for Option<nul>: requires nul (or _)")
                return
            if not has_null:
                self._error("NVC225", path, "Non-exhaustive match for Option<T>: requires nul plus catch-all")
            else:
                self._error("NVC225", path, "Cannot prove exhaustive Option<T> match without catch-all (_) in v0.1")
            return
        self._error("NVC226", path, "Cannot prove match exhaustiveness without catch-all (_) for this subject type")

    def _merge_branch_types(self, left: NovaType, right: NovaType, path: str) -> NovaType:
        if left.kind == "void" and right.kind == "void":
            return TYPE_VOID
        if left.kind == "void":
            return right
        if right.kind == "void":
            return left
        return self._merge_expr_types(left, right, path)

    def _merge_expr_types(self, left: NovaType, right: NovaType, path: str) -> NovaType:
        if left == right:
            return left
        if left.kind == "unknown":
            return right
        if right.kind == "unknown":
            return left
        if left.kind == "nul":
            return t_option(right)
        if right.kind == "nul":
            return t_option(left)
        if left.kind == "Option" and right.kind == "Option":
            return t_option(self._merge_expr_types(left.args[0], right.args[0], path))
        if left.kind == "rst" and right.kind == "rst":
            return t_result(
                self._merge_expr_types(left.args[0], right.args[0], path),
                self._merge_expr_types(left.args[1], right.args[1], path),
            )
        if left.kind == "array" and right.kind == "array":
            return t_array(self._merge_expr_types(left.args[0], right.args[0], path))
        self._error("NVC230", path, f"Incompatible branch types: {type_to_string(left)} vs {type_to_string(right)}")
        return TYPE_UNKNOWN

    def _function_type_from_decl(self, stmt: Dict[str, Any], path: str) -> NovaType:
        param_types: List[NovaType] = []
        for idx, param in enumerate(stmt.get("params", [])):
            if isinstance(param, str):
                param_types.append(TYPE_UNKNOWN)
            else:
                param_types.append(self._resolve_type_ref(param.get("annotation"), f"{path}.params[{idx}].annotation"))
        return_type = self._resolve_type_ref(stmt.get("return_type"), f"{path}.return_type")
        return t_fn(param_types, return_type)

    def _resolve_type_ref(self, type_ref: Optional[Dict[str, Any]], path: str) -> NovaType:
        if type_ref is None:
            return TYPE_UNKNOWN
        name = type_ref["name"]
        args = [self._resolve_type_ref(arg, f"{path}.args[{idx}]") for idx, arg in enumerate(type_ref.get("args", []))]
        primitive = {"str": TYPE_STR, "num": TYPE_NUM, "bool": TYPE_BOOL, "nul": TYPE_NUL, "mdl": TYPE_MDL, "err": TYPE_ERR, "any": TYPE_ANY}
        aliases = {"string": "str", "number": "num", "boolean": "bool", "null": "nul", "module": "mdl", "error": "err"}
        canonical_name = aliases.get(name, name)
        if canonical_name == "Option":
            if len(args) != 1:
                self._error("NVC400", path, "Option<T> expects exactly 1 type argument")
                return t_option(TYPE_UNKNOWN)
            return t_option(args[0])
        if canonical_name == "rst":
            if len(args) != 2:
                self._error("NVC401", path, "rst<T, E> expects exactly 2 type arguments")
                return t_result(TYPE_UNKNOWN, TYPE_UNKNOWN)
            return t_result(args[0], args[1])
        if canonical_name in primitive:
            if args:
                self._error("NVC402", path, f"Type '{canonical_name}' cannot have generic arguments")
            return primitive[canonical_name]
        if args:
            self._error("NVC403", path, "Advanced generics are not supported in v0.1")
            return NovaType(f"named:{canonical_name}")
        return NovaType(f"named:{canonical_name}")

    def _validate_err_payload(self, tp: NovaType, path: str) -> None:
        if tp.kind != "object":
            self._error("NVC340", path, "err payload must be object {code: str, msg: str}")
            return
        fields = dict(tp.fields)
        if "code" not in fields:
            self._error("NVC341", path, "err payload requires 'code'")
        else:
            self._expect_assignable(fields["code"], TYPE_STR, "NVC341", f"{path}.code", "err.code must be str")
        if "msg" not in fields:
            self._error("NVC342", path, "err payload requires 'msg'")
        else:
            self._expect_assignable(fields["msg"], TYPE_STR, "NVC342", f"{path}.msg", "err.msg must be str")

    def _extract_route_method_name(self, expr: Dict[str, Any], env: Env, path: str) -> Optional[str]:
        if expr["type"] == "Identifier":
            return expr["name"]
        if expr["type"] == "StringLiteral":
            self._error("NVC302", path, "rte method must be keyword (GET/POST/PUT/PATCH/DELETE), not string")
            return expr["value"]
        self._check_expr(expr, env, path)
        self._error("NVC302", path, "rte method must be keyword identifier (GET/POST/PUT/PATCH/DELETE)")
        return None

    def _current_module_result_type(self) -> NovaType:
        if not self._module_result_stack:
            return TYPE_UNKNOWN
        return self._module_result_stack[-1]

    def _is_valid_route_format(self, expr: Dict[str, Any]) -> bool:
        if expr["type"] == "Identifier":
            return expr["name"] in {"json", "toon"}
        if expr["type"] == "StringLiteral":
            return expr["value"] in {"json", "toon"}
        return False

    def _literal_type_from_node(self, node: Dict[str, Any]) -> NovaType:
        if node["type"] == "StringLiteral":
            return TYPE_STR
        if node["type"] == "NumberLiteral":
            return TYPE_NUM
        if node["type"] == "BooleanLiteral":
            return TYPE_BOOL
        if node["type"] == "NullLiteral":
            return TYPE_NUL
        return TYPE_UNKNOWN

    def _is_comparable(self, left: NovaType, right: NovaType) -> bool:
        if left.kind in {"unknown", "any"} or right.kind in {"unknown", "any"}:
            return True
        if left == right:
            return True
        if left.kind == "Option" and right.kind == "nul":
            return True
        if right.kind == "Option" and left.kind == "nul":
            return True
        return False

    def _expect_assignable(self, actual: NovaType, expected: NovaType, code: str, path: str, message: str) -> None:
        if not self._is_assignable(actual, expected):
            self._error(code, path, message)

    def _is_assignable(self, actual: NovaType, expected: NovaType) -> bool:
        if expected.kind in {"unknown", "any"} or actual.kind in {"unknown", "any"}:
            return True
        if actual == expected:
            return True
        if expected.kind == "Option":
            inner = expected.args[0]
            if actual.kind == "nul":
                return True
            if actual.kind == "Option":
                return self._is_assignable(actual.args[0], inner)
            return self._is_assignable(actual, inner)
        if expected.kind == "rst":
            if actual.kind != "rst":
                return False
            return self._is_assignable(actual.args[0], expected.args[0]) and self._is_assignable(actual.args[1], expected.args[1])
        if expected.kind == "array":
            if actual.kind != "array":
                return False
            return self._is_assignable(actual.args[0], expected.args[0])
        if expected.kind == "object":
            if actual.kind != "object":
                return False
            expected_fields = dict(expected.fields)
            actual_fields = dict(actual.fields)
            if expected_fields.keys() != actual_fields.keys():
                return False
            return all(self._is_assignable(actual_fields[k], v) for k, v in expected_fields.items())
        if expected.kind == "fn":
            if actual.kind != "fn" or len(actual.args) != len(expected.args):
                return False
            return all(self._is_assignable(a, b) for a, b in zip(actual.args, expected.args))
        return False

    def _unwrap_public(self, stmt: Dict[str, Any]) -> Dict[str, Any]:
        if stmt["type"] == "PublicDecl":
            return stmt["declaration"]
        return stmt

    def _error(self, code: str, path: str, message: str) -> None:
        self._diagnostics.append(Diagnostic(code=code, path=path, message=message))

    def _sorted_diagnostics(self) -> List[Diagnostic]:
        return sorted(self._diagnostics, key=lambda d: (d.path, d.code, d.message))


def check_ast(ast: Dict[str, Any]) -> CheckReport:
    return Checker().check(ast)


def format_diagnostics(diagnostics: Iterable[Diagnostic]) -> str:
    return "\n".join(f"[{d.code}] {d.path}: {d.message}" for d in diagnostics)
