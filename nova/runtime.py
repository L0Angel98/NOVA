from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse
from urllib import request as urllib_request

from .db_ir import (
    DbIr,
    DbIrError,
    InMemoryDbIrAdapter,
    apply_clause as apply_db_clause,
    build_ir_from_table_stmt,
    compile_plan as compile_db_plan,
    plan_to_dict,
)
from .parser import parse_nova
from .toon import ToonDecodeError, decode_toon, encode_toon


ERROR_STATUS_BY_CODE = {
    "BAD_REQUEST": 400,
    "INVALID_INPUT": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "ROUTE_NOT_FOUND": 404,
    "METHOD_NOT_ALLOWED": 405,
    "CONFLICT": 409,
    "UNPROCESSABLE": 422,
    "TOO_MANY_REQUESTS": 429,
    "INTERNAL_ERROR": 500,
    "NOT_IMPLEMENTED": 501,
    "CAP_FORBIDDEN": 403,
    "CAP_DECLARATION_REQUIRED": 403,
}

ALLOWED_CAPS = {"net", "db", "env", "fs"}


class RuntimeBuildError(ValueError):
    pass


class RuntimeExecError(ValueError):
    def __init__(self, code: str, msg: str, status: Optional[int] = None, details: Any = None) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg
        self.status = status
        self.details = details


@dataclass
class RstValue:
    kind: str
    value: Any


@dataclass
class QueryState:
    ir: Optional[DbIr] = None


class Scope:
    def __init__(self, parent: Optional["Scope"] = None) -> None:
        self.parent = parent
        self.values: Dict[str, Any] = {}

    def define(self, name: str, value: Any) -> None:
        self.values[name] = value

    def get(self, name: str) -> Any:
        cur: Optional[Scope] = self
        while cur is not None:
            if name in cur.values:
                return cur.values[name]
            cur = cur.parent
        raise RuntimeExecError("BAD_REQUEST", f"undefined identifier '{name}'", status=400)

    def copy_shallow(self) -> "Scope":
        new_scope = Scope(self.parent)
        new_scope.values = dict(self.values)
        return new_scope


@dataclass
class UserFunction:
    decl: Dict[str, Any]
    closure: Scope


@dataclass
class RouteDef:
    method: str
    path: str
    fmt: str
    pattern: re.Pattern[str]
    param_names: List[str]
    required_caps: frozenset[str]
    body: List[Dict[str, Any]]
    closure: Scope


@dataclass
class RequestContext:
    request_id: str
    method: str
    path: str
    params: Dict[str, Any]
    query: Dict[str, Any]
    headers: Dict[str, Any]
    body: Any
    ctx: Dict[str, Any]


@dataclass
class DispatchReply:
    status: int
    payload: Any
    fmt: str


class InMemoryDB:
    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        self.next_ids: Dict[str, int] = {}

    def read(self, query: QueryState, evaluator: "NovaRuntime", route_scope: Scope) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in self._rows_for(query.table)]
        rows = self._filter_rows(rows, query, evaluator, route_scope)
        rows = self._order_rows(rows, query)
        if query.limit is not None:
            rows = rows[: query.limit]
        return rows

    def create(self, query: QueryState, payload: Any) -> Dict[str, Any]:
        table = self._require_table(query)
        if not isinstance(payload, dict):
            raise RuntimeExecError("BAD_REQUEST", "db.create expects object payload", status=400)
        row = dict(payload)
        if "id" not in row:
            row["id"] = self._next_id(table)
        self.tables.setdefault(table, []).append(row)
        return dict(row)

    def update(self, query: QueryState, payload: Any, evaluator: "NovaRuntime", route_scope: Scope) -> Dict[str, Any]:
        table = self._require_table(query)
        if not isinstance(payload, dict):
            raise RuntimeExecError("BAD_REQUEST", "db.update expects object payload", status=400)
        updated: List[Dict[str, Any]] = []
        rows = self.tables.setdefault(table, [])
        for row in rows:
            if self._row_matches(row, query, evaluator, route_scope):
                row.update(payload)
                updated.append(dict(row))
        return {"updated": updated, "count": len(updated)}

    def delete(self, query: QueryState, evaluator: "NovaRuntime", route_scope: Scope) -> Dict[str, Any]:
        table = self._require_table(query)
        rows = self.tables.setdefault(table, [])
        kept: List[Dict[str, Any]] = []
        deleted_count = 0
        for row in rows:
            if self._row_matches(row, query, evaluator, route_scope):
                deleted_count += 1
            else:
                kept.append(row)
        self.tables[table] = kept
        return {"deleted": deleted_count}

    def _rows_for(self, table: Optional[str]) -> List[Dict[str, Any]]:
        if table is None:
            raise RuntimeExecError("BAD_REQUEST", "tb must be declared before db operation", status=400)
        return self.tables.setdefault(table, [])

    def _require_table(self, query: QueryState) -> str:
        if query.table is None:
            raise RuntimeExecError("BAD_REQUEST", "tb must be declared before db operation", status=400)
        return query.table

    def _next_id(self, table: str) -> int:
        current = self.next_ids.get(table, 1)
        self.next_ids[table] = current + 1
        return current

    def _filter_rows(
        self,
        rows: List[Dict[str, Any]],
        query: QueryState,
        evaluator: "NovaRuntime",
        route_scope: Scope,
    ) -> List[Dict[str, Any]]:
        if query.where_expr is None:
            return rows
        return [row for row in rows if self._row_matches(row, query, evaluator, route_scope)]

    def _row_matches(
        self,
        row: Dict[str, Any],
        query: QueryState,
        evaluator: "NovaRuntime",
        route_scope: Scope,
    ) -> bool:
        if query.where_expr is None:
            return True
        row_scope = Scope(route_scope)
        for key, value in row.items():
            row_scope.define(key, value)
        result = evaluator._eval_expr(query.where_expr, row_scope, None, allow_undefined_identifier=False)
        return bool(result)

    def _order_rows(self, rows: List[Dict[str, Any]], query: QueryState) -> List[Dict[str, Any]]:
        if query.order_field is None:
            return rows
        reverse = query.order_direction == "desc"
        return sorted(rows, key=lambda row: row.get(query.order_field), reverse=reverse)


class RstBuiltin:
    def ok(self, value: Any) -> RstValue:
        return RstValue("ok", value)

    def err(self, value: Any) -> RstValue:
        return RstValue("err", value)


class OptionBuiltin:
    def some(self, value: Any) -> Any:
        return value

    def none(self) -> None:
        return None


class DbFacade:
    def __init__(self, runtime: "NovaRuntime", route_scope: Scope, query: QueryState) -> None:
        self.runtime = runtime
        self.route_scope = route_scope
        self.query = query

    def read(self) -> Any:
        return self.runtime._db_read(self.route_scope, self.query)

    def create(self, payload: Any) -> Any:
        return self.runtime._db_create(self.route_scope, self.query, payload)

    def update(self, payload: Any) -> Any:
        return self.runtime._db_update(self.route_scope, self.query, payload)

    def delete(self) -> Any:
        return self.runtime._db_delete(self.route_scope, self.query)

    def plan(self) -> Dict[str, Any]:
        return self.runtime._db_plan_dict(self.route_scope, self.query)


class EnvFacade:
    def __init__(self, runtime: "NovaRuntime", route_scope: Scope) -> None:
        self.runtime = runtime
        self.route_scope = route_scope

    def get(self, key: Any, default: Any = None) -> Any:
        self.runtime._require_cap(self.route_scope, "env", "env.get")
        return os.environ.get(str(key), default)

    def keys(self) -> List[str]:
        self.runtime._require_cap(self.route_scope, "env", "env.keys")
        return sorted(os.environ.keys())


class FsFacade:
    def __init__(self, runtime: "NovaRuntime", route_scope: Scope) -> None:
        self.runtime = runtime
        self.route_scope = route_scope

    def read(self, path: Any) -> str:
        self.runtime._require_cap(self.route_scope, "fs", "fs.read")
        file_path = Path(str(path))
        try:
            return file_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RuntimeExecError("NOT_FOUND", f"file not found: {file_path}") from exc

    def write(self, path: Any, content: Any) -> Dict[str, Any]:
        self.runtime._require_cap(self.route_scope, "fs", "fs.write")
        file_path = Path(str(path))
        text = str(content)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text, encoding="utf-8")
        return {"path": str(file_path), "bytes": len(text.encode("utf-8"))}

    def exists(self, path: Any) -> bool:
        self.runtime._require_cap(self.route_scope, "fs", "fs.exists")
        return Path(str(path)).exists()


class NetFacade:
    def __init__(self, runtime: "NovaRuntime", route_scope: Scope) -> None:
        self.runtime = runtime
        self.route_scope = route_scope

    def get(self, url: Any, timeout: Any = 5) -> Dict[str, Any]:
        self.runtime._require_cap(self.route_scope, "net", "net.get")
        return self._request("GET", url, None, timeout)

    def post(self, url: Any, payload: Any = None, timeout: Any = 5) -> Dict[str, Any]:
        self.runtime._require_cap(self.route_scope, "net", "net.post")
        return self._request("POST", url, payload, timeout)

    def _request(self, method: str, url: Any, payload: Any, timeout: Any) -> Dict[str, Any]:
        try:
            timeout_num = float(timeout)
        except Exception as exc:
            raise RuntimeExecError("BAD_REQUEST", f"invalid timeout value: {timeout}") from exc

        target = str(url)
        data = None
        headers = {"User-Agent": "nova-runtime/0.1"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = urllib_request.Request(target, data=data, method=method, headers=headers)
        try:
            with urllib_request.urlopen(req, timeout=timeout_num) as res:
                raw = res.read()
                text = raw.decode("utf-8", errors="replace")
                return {"status": res.status, "body": text, "headers": dict(res.headers.items())}
        except Exception as exc:
            raise RuntimeExecError("BAD_REQUEST", f"net request failed: {exc}") from exc


class NovaRuntime:
    def __init__(self, ast: Dict[str, Any], capabilities: Optional[List[str] | set[str] | tuple[str, ...]] = None) -> None:
        self.ast = ast
        self.db = InMemoryDbIrAdapter()
        self.routes: List[RouteDef] = []
        self.global_scope = Scope()
        self._request_counter = 0
        self.granted_caps = self._normalize_granted_caps(capabilities)

        self.global_scope.define("rst", RstBuiltin())
        self.global_scope.define("Option", OptionBuiltin())
        self.global_scope.define("to_num", self._to_num)
        self.global_scope.define("to_str", self._to_str)
        self.global_scope.define("json", "json")
        self.global_scope.define("toon", "toon")

        self._load_statements(self.ast.get("body", []), self.global_scope)

    @classmethod
    def from_source(
        cls,
        source: str,
        capabilities: Optional[List[str] | set[str] | tuple[str, ...]] = None,
    ) -> "NovaRuntime":
        return cls(parse_nova(source), capabilities=capabilities)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        capabilities: Optional[List[str] | set[str] | tuple[str, ...]] = None,
    ) -> "NovaRuntime":
        source = Path(path).read_text(encoding="utf-8")
        return cls.from_source(source, capabilities=capabilities)

    def dispatch(
        self,
        method: str,
        raw_path: str,
        headers: Dict[str, Any],
        body: Any,
    ) -> Tuple[int, Any]:
        result = self._dispatch_core(method, raw_path, headers, body)
        return result.status, result.payload

    def dispatch_http(
        self,
        method: str,
        raw_path: str,
        headers: Dict[str, Any],
        body: Any,
    ) -> DispatchReply:
        return self._dispatch_core(method, raw_path, headers, body)

    def _dispatch_core(
        self,
        method: str,
        raw_path: str,
        headers: Dict[str, Any],
        body: Any,
    ) -> DispatchReply:
        parsed = urlparse(raw_path)
        path = parsed.path or "/"
        query = self._normalize_query(parse_qs(parsed.query, keep_blank_values=True))

        route, params, method_allowed = self._match_route(method, path)
        if route is None:
            if method_allowed:
                status, payload = self._error_payload("METHOD_NOT_ALLOWED", "method not allowed", status=405, fmt="json")
                return DispatchReply(status=status, payload=payload, fmt="json")
            status, payload = self._error_payload("ROUTE_NOT_FOUND", "route not found", status=404, fmt="json")
            return DispatchReply(status=status, payload=payload, fmt="json")

        request_id = self._next_request_id()
        ctx = {
            "request_id": request_id,
            "method": method,
            "path": path,
            "timestamp_ms": int(time.time() * 1000),
        }

        request = RequestContext(
            request_id=request_id,
            method=method,
            path=path,
            params=params,
            query=query,
            headers=headers,
            body=body,
            ctx=ctx,
        )

        missing_route_caps = sorted([cap for cap in route.required_caps if cap not in self.granted_caps])
        if missing_route_caps:
            status, payload = self._error_payload(
                "CAP_FORBIDDEN",
                f"route requires missing capabilities: {', '.join(missing_route_caps)}",
                status=403,
                details={"required": sorted(route.required_caps), "granted": sorted(self.granted_caps)},
                fmt=route.fmt,
            )
            return DispatchReply(status=status, payload=payload, fmt=route.fmt)

        try:
            response_value = self._execute_route(route, request)
            status, payload = self._to_http_response(response_value, route.fmt)
            return DispatchReply(status=status, payload=payload, fmt=route.fmt)
        except RuntimeExecError as exc:
            details = exc.details if exc.details is not None else None
            status, payload = self._error_payload(exc.code, exc.msg, status=exc.status, details=details, fmt=route.fmt)
            return DispatchReply(status=status, payload=payload, fmt=route.fmt)
        except Exception:
            trace = traceback.format_exc()
            status, payload = self._error_payload(
                "INTERNAL_ERROR",
                "unexpected runtime failure",
                status=500,
                details={"trace": trace},
                fmt=route.fmt,
            )
            return DispatchReply(status=status, payload=payload, fmt=route.fmt)

    def _load_statements(self, statements: List[Dict[str, Any]], scope: Scope) -> None:
        for stmt in statements:
            target = stmt["declaration"] if stmt["type"] == "PublicDecl" else stmt
            typ = target["type"]

            if typ == "ModuleDecl":
                module_scope = Scope(scope)
                self._load_statements(target.get("body", []), module_scope)
                continue

            if typ == "ImportStmt":
                continue

            if typ == "FunctionDecl":
                scope.define(target["name"], UserFunction(target, scope.copy_shallow()))
                continue

            if typ == "LetStmt":
                value = self._eval_expr(target["value"], scope, None, allow_undefined_identifier=False)
                scope.define(target["name"], value)
                continue

            if typ == "RouteDecl":
                self.routes.append(self._compile_route(target, scope.copy_shallow()))
                continue

    def _compile_route(self, stmt: Dict[str, Any], closure: Scope) -> RouteDef:
        method = self._expect_route_method(stmt["method"])
        path = self._expect_static_string(stmt["path"], "rte path")
        fmt = self._expect_route_format(stmt["format"])
        required_caps = self._extract_required_caps(stmt.get("body", []))

        pattern, param_names = self._compile_path_pattern(path)
        return RouteDef(
            method=method,
            path=path,
            fmt=fmt,
            pattern=pattern,
            param_names=param_names,
            required_caps=frozenset(required_caps),
            body=stmt.get("body", []),
            closure=closure,
        )

    def _compile_path_pattern(self, path: str) -> Tuple[re.Pattern[str], List[str]]:
        normalized = path.strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        if normalized != "/" and normalized.endswith("/"):
            normalized = normalized[:-1]

        parts = [p for p in normalized.split("/") if p]
        regex_parts: List[str] = []
        params: List[str] = []
        for part in parts:
            if part.startswith(":") and len(part) > 1:
                name = part[1:]
                params.append(name)
                regex_parts.append(f"(?P<{name}>[^/]+)")
            else:
                regex_parts.append(re.escape(part))

        if not regex_parts:
            pattern = re.compile(r"^/$")
        else:
            pattern = re.compile(r"^/" + "/".join(regex_parts) + r"$")
        return pattern, params

    def _match_route(self, method: str, path: str) -> Tuple[Optional[RouteDef], Dict[str, Any], bool]:
        normalized = path if path.startswith("/") else f"/{path}"
        method = method.upper()
        path_matched = False
        for route in self.routes:
            match = route.pattern.match(normalized)
            if not match:
                continue
            path_matched = True
            if route.method != method:
                continue
            params = {k: self._auto_cast(v) for k, v in match.groupdict().items()}
            return route, params, True
        return None, {}, path_matched

    def _execute_route(self, route: RouteDef, request: RequestContext) -> Any:
        scope = Scope(route.closure)
        scope.define("params", request.params)
        scope.define("query", request.query)
        scope.define("headers", request.headers)
        scope.define("body", request.body)
        scope.define("ctx", request.ctx)
        scope.define("__route_caps_declared", set(route.required_caps))

        query = QueryState()
        scope.define("db", DbFacade(self, scope, query))
        scope.define("env", EnvFacade(self, scope))
        scope.define("fs", FsFacade(self, scope))
        scope.define("net", NetFacade(self, scope))
        scope.define("db_ir", {})

        value = self._exec_block(route.body, scope, query)
        if value is None:
            raise RuntimeExecError("INTERNAL_ERROR", "route did not produce a response value", status=500)
        return value

    def _db_plan_dict(self, scope: Scope, query: QueryState) -> Dict[str, Any]:
        plan = self._compile_active_plan(scope, query)
        return plan_to_dict(plan)

    def _db_read(self, scope: Scope, query: QueryState) -> Any:
        self._require_cap(scope, "db", "db.read")
        plan = self._compile_active_plan(scope, query)
        return self.db.read(plan, lambda row, whe: self._row_matches_plan(row, whe, scope))

    def _db_create(self, scope: Scope, query: QueryState, payload: Any) -> Any:
        self._require_cap(scope, "db", "db.create")
        plan = self._compile_active_plan(scope, query)
        try:
            return self.db.create(plan, payload)
        except DbIrError as exc:
            raise RuntimeExecError("BAD_REQUEST", str(exc), status=400) from exc

    def _db_update(self, scope: Scope, query: QueryState, payload: Any) -> Any:
        self._require_cap(scope, "db", "db.update")
        plan = self._compile_active_plan(scope, query)
        try:
            return self.db.update(plan, payload, lambda row, whe: self._row_matches_plan(row, whe, scope))
        except DbIrError as exc:
            raise RuntimeExecError("BAD_REQUEST", str(exc), status=400) from exc

    def _db_delete(self, scope: Scope, query: QueryState) -> Any:
        self._require_cap(scope, "db", "db.delete")
        plan = self._compile_active_plan(scope, query)
        return self.db.delete(plan, lambda row, whe: self._row_matches_plan(row, whe, scope))

    def _compile_active_plan(self, scope: Scope, query: QueryState):
        if query.ir is None:
            raise RuntimeExecError("BAD_REQUEST", "tb must be declared before db operation", status=400)
        try:
            plan = compile_db_plan(
                query.ir,
                eval_table_name=lambda expr: self._eval_table_name(expr, scope, query),
                eval_expr=lambda expr: self._eval_expr(expr, scope, query, allow_undefined_identifier=True),
            )
            scope.define("db_ir", plan_to_dict(plan))
            return plan
        except DbIrError as exc:
            raise RuntimeExecError("BAD_REQUEST", str(exc), status=400) from exc

    def _row_matches_plan(self, row: Dict[str, Any], where_expr: Optional[Dict[str, Any]], scope: Scope) -> bool:
        if where_expr is None:
            return True
        row_scope = Scope(scope)
        for key, value in row.items():
            row_scope.define(key, value)
        result = self._eval_expr(where_expr, row_scope, None, allow_undefined_identifier=False)
        return bool(result)

    def _exec_block(self, body: List[Dict[str, Any]], scope: Scope, query: QueryState) -> Any:
        last_value: Any = None
        for stmt in body:
            value, terminal = self._exec_statement(stmt, scope, query)
            if value is not None:
                last_value = value
            if terminal:
                return value
        return last_value

    def _exec_statement(self, stmt: Dict[str, Any], scope: Scope, query: QueryState) -> Tuple[Any, bool]:
        typ = stmt["type"]

        if typ == "PublicDecl":
            return self._exec_statement(stmt["declaration"], scope, query)

        if typ == "LetStmt":
            value = self._eval_expr(stmt["value"], scope, query)
            scope.define(stmt["name"], value)
            return None, False

        if typ == "IfStmt":
            cond = self._eval_expr(stmt["condition"], scope, query)
            if not isinstance(cond, bool):
                cond = bool(cond)

            if cond:
                result = self._exec_block(stmt.get("then", []), Scope(scope), query)
                return result, isinstance(result, RstValue)

            else_branch = stmt.get("else")
            if else_branch is None:
                return None, False
            if else_branch["type"] == "ElseIf":
                return self._exec_statement(else_branch["branch"], Scope(scope), query)
            if else_branch["type"] == "ElseBlock":
                result = self._exec_block(else_branch.get("body", []), Scope(scope), query)
                return result, isinstance(result, RstValue)
            return None, False

        if typ == "GuardStmt":
            code_value = self._eval_expr(stmt["code"], scope, query)
            code = str(code_value)
            for expr in stmt.get("targets", []):
                value = self._eval_expr(expr, scope, query)
                if not self._guard_value_present(value):
                    label = self._expr_label(expr)
                    return RstValue(
                        "err",
                        {
                            "code": code,
                            "msg": f"missing required value: {label}",
                        },
                    ), True
            return None, False

        if typ == "ExprStmt":
            value = self._eval_expr(stmt["expression"], scope, query)
            return value, isinstance(value, RstValue)

        if typ == "ErrorStmt":
            payload = self._eval_expr(stmt["value"], scope, query)
            err_payload = self._normalize_err_payload(payload)
            return RstValue("err", err_payload), True

        if typ == "TableStmt":
            try:
                query.ir = build_ir_from_table_stmt(stmt)
            except DbIrError as exc:
                raise RuntimeExecError("BAD_REQUEST", str(exc), status=400) from exc

            # Declarative shortcuts:
            # - tb users.get
            # - tb users.q { whe ... lim ... ord ... }
            op = stmt.get("op")
            if op == "get" or (op == "q" and bool(stmt.get("query"))):
                return self._db_read(scope, query), False

            scope.define("db_ir", self._db_plan_dict(scope, query))
            return None, False

        if typ == "WhereStmt":
            if query.ir is None:
                raise RuntimeExecError("BAD_REQUEST", "whe requires prior tb statement", status=400)
            try:
                apply_db_clause(query.ir, stmt)
            except DbIrError as exc:
                raise RuntimeExecError("BAD_REQUEST", str(exc), status=400) from exc
            scope.define("db_ir", self._db_plan_dict(scope, query))
            return None, False

        if typ == "LimitStmt":
            if query.ir is None:
                raise RuntimeExecError("BAD_REQUEST", "lim requires prior tb statement", status=400)
            try:
                apply_db_clause(query.ir, stmt)
            except DbIrError as exc:
                raise RuntimeExecError("BAD_REQUEST", str(exc), status=400) from exc
            scope.define("db_ir", self._db_plan_dict(scope, query))
            return None, False

        if typ == "OrderStmt":
            if query.ir is None:
                raise RuntimeExecError("BAD_REQUEST", "ord requires prior tb statement", status=400)
            try:
                apply_db_clause(query.ir, stmt)
            except DbIrError as exc:
                raise RuntimeExecError("BAD_REQUEST", str(exc), status=400) from exc
            scope.define("db_ir", self._db_plan_dict(scope, query))
            return None, False

        if typ == "CapStmt":
            return None, False

        if typ == "FunctionDecl":
            scope.define(stmt["name"], UserFunction(stmt, scope.copy_shallow()))
            return None, False

        if typ == "ModuleDecl":
            module_scope = Scope(scope)
            self._exec_block(stmt.get("body", []), module_scope, query)
            return None, False

        return None, False

    def _eval_expr(
        self,
        expr: Dict[str, Any],
        scope: Scope,
        query: Optional[QueryState],
        allow_undefined_identifier: bool = False,
    ) -> Any:
        typ = expr["type"]

        if typ == "StringLiteral":
            return expr["value"]
        if typ == "NumberLiteral":
            return self._to_num(expr["value"])
        if typ == "BooleanLiteral":
            return bool(expr["value"])
        if typ == "NullLiteral":
            return None
        if typ == "Identifier":
            name = expr["name"]
            try:
                return scope.get(name)
            except RuntimeExecError:
                if allow_undefined_identifier:
                    return name
                raise
        if typ == "ArrayLiteral":
            return [self._eval_expr(item, scope, query) for item in expr.get("items", [])]
        if typ == "ObjectLiteral":
            return {field["key"]: self._eval_expr(field["value"], scope, query) for field in expr.get("fields", [])}
        if typ == "MemberExpr":
            obj = self._eval_expr(expr["object"], scope, query)
            prop = expr["property"]
            if isinstance(obj, dict):
                return obj.get(prop)
            if hasattr(obj, prop):
                return getattr(obj, prop)
            return None
        if typ == "CallExpr":
            callee = self._eval_expr(expr["callee"], scope, query)
            args = [self._eval_expr(arg, scope, query) for arg in expr.get("args", [])]
            return self._call_value(callee, args, scope, query)
        if typ == "UnaryExpr":
            inner = self._eval_expr(expr["expression"], scope, query)
            op = expr["operator"]
            if op == "-":
                return -self._to_num(inner)
            if op == "!":
                return not bool(inner)
            raise RuntimeExecError("BAD_REQUEST", f"unsupported unary operator '{op}'", status=400)
        if typ == "BinaryExpr":
            return self._eval_binary(expr, scope, query)
        if typ == "MatchExpr":
            return self._eval_match(expr, scope, query)
        if typ == "AwaitExpr":
            value = self._eval_expr(expr["expression"], scope, query)
            if isinstance(value, _AsyncThunk):
                return value.run()
            return value
        if typ == "AsyncExpr":
            captured = scope.copy_shallow()
            body = expr.get("body", [])
            return _AsyncThunk(lambda: self._exec_block(body, Scope(captured), QueryState()))

        raise RuntimeExecError("BAD_REQUEST", f"unsupported expression type '{typ}'", status=400)

    def _eval_binary(self, expr: Dict[str, Any], scope: Scope, query: Optional[QueryState]) -> Any:
        op = expr["operator"]
        left = self._eval_expr(expr["left"], scope, query)
        right = self._eval_expr(expr["right"], scope, query)

        if op == "+":
            if isinstance(left, str) or isinstance(right, str):
                return f"{left}{right}"
            return self._to_num(left) + self._to_num(right)
        if op == "-":
            return self._to_num(left) - self._to_num(right)
        if op == "*":
            return self._to_num(left) * self._to_num(right)
        if op == "/":
            divisor = self._to_num(right)
            if divisor == 0:
                raise RuntimeExecError("BAD_REQUEST", "division by zero", status=400)
            return self._to_num(left) / divisor
        if op == "==":
            return self._values_equal(left, right)
        if op == "!=":
            return not self._values_equal(left, right)
        if op == "<":
            return self._to_num(left) < self._to_num(right)
        if op == "<=":
            return self._to_num(left) <= self._to_num(right)
        if op == ">":
            return self._to_num(left) > self._to_num(right)
        if op == ">=":
            return self._to_num(left) >= self._to_num(right)
        if op == "&&":
            return bool(left) and bool(right)
        if op == "||":
            return bool(left) or bool(right)
        raise RuntimeExecError("BAD_REQUEST", f"unsupported binary operator '{op}'", status=400)

    def _eval_match(self, expr: Dict[str, Any], scope: Scope, query: Optional[QueryState]) -> Any:
        subject = self._eval_expr(expr["subject"], scope, query)
        for case in expr.get("cases", []):
            if self._matches_pattern(subject, case["pattern"], scope, query):
                return self._eval_expr(case["value"], scope, query)
        raise RuntimeExecError("BAD_REQUEST", "non-exhaustive match at runtime", status=400)

    def _matches_pattern(self, subject: Any, pattern: Dict[str, Any], scope: Scope, query: Optional[QueryState]) -> bool:
        typ = pattern["type"]
        if typ in {"WildcardPattern", "IdentifierPattern"}:
            return True
        if typ == "LiteralPattern":
            return self._values_equal(subject, self._eval_expr(pattern["value"], scope, query))
        if typ == "ExprPattern":
            return self._values_equal(subject, self._eval_expr(pattern["value"], scope, query))
        return False

    def _call_value(self, callee: Any, args: List[Any], scope: Scope, query: Optional[QueryState]) -> Any:
        if isinstance(callee, UserFunction):
            fn_scope = Scope(callee.closure)
            params = callee.decl.get("params", [])
            for idx, param in enumerate(params):
                if isinstance(param, str):
                    pname = param
                else:
                    pname = param["name"]
                fn_scope.define(pname, args[idx] if idx < len(args) else None)
            return self._exec_block(callee.decl.get("body", []), fn_scope, query or QueryState())

        if callable(callee):
            return callee(*args)

        raise RuntimeExecError("BAD_REQUEST", "call target is not callable", status=400)

    def _eval_table_name(self, expr: Dict[str, Any], scope: Scope, query: Optional[QueryState]) -> str:
        if expr["type"] == "Identifier":
            name = expr["name"]
            try:
                value = scope.get(name)
                return str(value)
            except RuntimeExecError:
                return name
        value = self._eval_expr(expr, scope, query)
        return str(value)

    def _normalize_err_payload(self, payload: Any) -> Dict[str, Any]:
        if isinstance(payload, RstValue):
            if payload.kind == "err":
                payload = payload.value
            else:
                payload = {"code": "INTERNAL_ERROR", "msg": "invalid ok payload in err"}

        if not isinstance(payload, dict):
            return {"code": "BAD_REQUEST", "msg": str(payload)}

        code = str(payload.get("code", "BAD_REQUEST"))
        msg = str(payload.get("msg", "error"))
        details = payload.get("details")
        out = {"code": code, "msg": msg}
        if details is not None:
            out["details"] = details
        return out

    def _to_http_response(self, value: Any, fmt: str = "json") -> Tuple[int, Any]:
        if fmt == "toon":
            if isinstance(value, RstValue):
                if value.kind == "ok":
                    return 200, self._json_safe(value.value)
                err_payload = self._normalize_err_payload(value.value)
                status = ERROR_STATUS_BY_CODE.get(err_payload["code"], 400)
                return status, err_payload
            return 200, self._json_safe(value)

        if isinstance(value, RstValue):
            if value.kind == "ok":
                return 200, {"ok": True, "data": self._json_safe(value.value)}
            err_payload = self._normalize_err_payload(value.value)
            status = ERROR_STATUS_BY_CODE.get(err_payload["code"], 400)
            payload = {"ok": False, "error": err_payload}
            return status, payload
        return 200, {"ok": True, "data": self._json_safe(value)}

    def _error_payload(
        self,
        code: str,
        msg: str,
        status: Optional[int] = None,
        details: Any = None,
        fmt: str = "json",
    ) -> Tuple[int, Any]:
        http_status = status if status is not None else ERROR_STATUS_BY_CODE.get(code, 500)
        if fmt == "toon":
            payload: Dict[str, Any] = {"code": code, "msg": msg}
            if details is not None:
                payload["details"] = self._json_safe(details)
            return http_status, payload

        payload_json: Dict[str, Any] = {"ok": False, "error": {"code": code, "msg": msg}}
        if details is not None:
            payload_json["error"]["details"] = self._json_safe(details)
        return http_status, payload_json

    def _normalize_granted_caps(
        self,
        capabilities: Optional[List[str] | set[str] | tuple[str, ...]],
    ) -> frozenset[str]:
        if capabilities is None:
            return frozenset()
        normalized = {str(item).strip() for item in capabilities if str(item).strip() != ""}
        invalid = sorted([cap for cap in normalized if cap not in ALLOWED_CAPS])
        if invalid:
            raise RuntimeBuildError(f"invalid runtime capabilities: {', '.join(invalid)}")
        return frozenset(normalized)

    def _extract_required_caps(self, body: List[Dict[str, Any]]) -> set[str]:
        caps: set[str] = set()
        for stmt in body:
            caps.update(self._extract_required_caps_from_stmt(stmt, top_level=True))
        if self._route_uses_table_stmt(body):
            caps.add("db")
        return caps

    def _extract_required_caps_from_stmt(self, stmt: Dict[str, Any], top_level: bool) -> set[str]:
        typ = stmt.get("type")
        if typ == "CapStmt":
            if not top_level:
                raise RuntimeBuildError("cap declarations must be top-level statements in rte body")
            return self._parse_cap_declaration(stmt["value"])

        nested_caps: set[str] = set()
        if typ == "IfStmt":
            for inner in stmt.get("then", []):
                nested_caps.update(self._extract_required_caps_from_stmt(inner, top_level=False))
            else_branch = stmt.get("else")
            if else_branch is not None:
                if else_branch.get("type") == "ElseIf":
                    nested_caps.update(self._extract_required_caps_from_stmt(else_branch["branch"], top_level=False))
                elif else_branch.get("type") == "ElseBlock":
                    for inner in else_branch.get("body", []):
                        nested_caps.update(self._extract_required_caps_from_stmt(inner, top_level=False))
        elif typ in {"FunctionDecl", "ModuleDecl", "RouteDecl"}:
            for inner in stmt.get("body", []):
                nested_caps.update(self._extract_required_caps_from_stmt(inner, top_level=False))
        elif typ == "PublicDecl":
            nested_caps.update(self._extract_required_caps_from_stmt(stmt["declaration"], top_level=False))
        return nested_caps

    def _route_uses_table_stmt(self, body: List[Dict[str, Any]]) -> bool:
        for stmt in body:
            if self._stmt_uses_table(stmt):
                return True
        return False

    def _stmt_uses_table(self, stmt: Dict[str, Any]) -> bool:
        typ = stmt.get("type")
        if typ == "TableStmt":
            return True
        if typ == "IfStmt":
            for inner in stmt.get("then", []):
                if self._stmt_uses_table(inner):
                    return True
            else_branch = stmt.get("else")
            if else_branch is not None:
                if else_branch.get("type") == "ElseIf":
                    if self._stmt_uses_table(else_branch["branch"]):
                        return True
                elif else_branch.get("type") == "ElseBlock":
                    for inner in else_branch.get("body", []):
                        if self._stmt_uses_table(inner):
                            return True
        if typ in {"FunctionDecl", "ModuleDecl", "RouteDecl"}:
            for inner in stmt.get("body", []):
                if self._stmt_uses_table(inner):
                    return True
        if typ == "PublicDecl":
            return self._stmt_uses_table(stmt["declaration"])
        return False

    def _parse_cap_declaration(self, expr: Dict[str, Any]) -> set[str]:
        values: List[str] = []
        if expr["type"] == "ArrayLiteral":
            for item in expr.get("items", []):
                values.append(self._cap_item_to_str(item))
        else:
            values.append(self._cap_item_to_str(expr))

        caps = {value.strip() for value in values if value.strip() != ""}
        invalid = sorted([cap for cap in caps if cap not in ALLOWED_CAPS])
        if invalid:
            raise RuntimeBuildError(f"cap declaration contains unsupported capability: {', '.join(invalid)}")
        return caps

    def _cap_item_to_str(self, expr: Dict[str, Any]) -> str:
        if expr["type"] == "StringLiteral":
            return str(expr["value"])
        if expr["type"] == "Identifier":
            return expr["name"]
        raise RuntimeBuildError("cap declaration must be static string/identifier list (no dynamic expressions)")

    def _require_cap(self, scope: Scope, cap: str, operation: str) -> None:
        try:
            declared = scope.get("__route_caps_declared")
        except RuntimeExecError:
            declared = set()
        declared_set = set(declared) if isinstance(declared, (set, list, tuple, frozenset)) else set()

        if cap not in declared_set:
            raise RuntimeExecError(
                "CAP_DECLARATION_REQUIRED",
                f"{operation} requires cap '{cap}' declared via cap [{cap}]",
                status=403,
                details={"required_cap": cap, "declared_caps": sorted(declared_set)},
            )

        if cap not in self.granted_caps:
            raise RuntimeExecError(
                "CAP_FORBIDDEN",
                f"{operation} blocked: runtime missing cap '{cap}'",
                status=403,
                details={"required_cap": cap, "granted_caps": sorted(self.granted_caps)},
            )

    def _expect_route_method(self, expr: Dict[str, Any]) -> str:
        if expr["type"] == "StringLiteral":
            raise RuntimeBuildError(
                "rte method must be keyword (GET/POST/PUT/PATCH/DELETE), not string literal"
            )
        if expr["type"] == "Identifier":
            method = expr["name"]
            allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"}
            if method not in allowed:
                raise RuntimeBuildError(f"Unsupported rte method '{method}'")
            return method
        raise RuntimeBuildError("rte method must be keyword identifier (GET/POST/PUT/PATCH/DELETE)")

    def _expect_route_format(self, expr: Dict[str, Any]) -> str:
        if expr["type"] == "Identifier":
            fmt = expr["name"]
        elif expr["type"] == "StringLiteral":
            fmt = str(expr["value"])
        else:
            raise RuntimeBuildError("rte format must be json or toon")
        if fmt not in {"json", "toon"}:
            raise RuntimeBuildError(f"Unsupported rte format '{fmt}'; expected json or toon")
        return fmt

    def _expect_static_string(self, expr: Dict[str, Any], label: str) -> str:
        if expr["type"] == "StringLiteral":
            return str(expr["value"])
        if expr["type"] == "Identifier":
            if expr["name"] in {"json", "toon"}:
                return expr["name"]
            try:
                value = self.global_scope.get(expr["name"])
            except RuntimeExecError:
                raise RuntimeBuildError(f"{label} must be static string literal")
            return str(value)
        raise RuntimeBuildError(f"{label} must be static string literal")

    def _guard_value_present(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True

    def _expr_label(self, expr: Dict[str, Any]) -> str:
        typ = expr.get("type")
        if typ == "Identifier":
            return expr["name"]
        if typ == "MemberExpr":
            return f"{self._expr_label(expr['object'])}.{expr['property']}"
        return "<expr>"

    def _normalize_query(self, query_map: Dict[str, List[str]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, values in query_map.items():
            if len(values) == 1:
                out[key] = self._auto_cast(values[0])
            else:
                out[key] = [self._auto_cast(v) for v in values]
        return out

    def _next_request_id(self) -> str:
        self._request_counter += 1
        return f"req-{self._request_counter:06d}"

    def _to_num(self, value: Any) -> float | int:
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text == "":
                raise RuntimeExecError("BAD_REQUEST", "expected number, got empty string", status=400)
            try:
                if "." in text:
                    return float(text)
                return int(text)
            except ValueError:
                raise RuntimeExecError("BAD_REQUEST", f"invalid number '{value}'", status=400)
        raise RuntimeExecError("BAD_REQUEST", f"expected number, got {type(value).__name__}", status=400)

    def _to_str(self, value: Any) -> str:
        if value is None:
            return "nul"
        return str(value)

    def _values_equal(self, left: Any, right: Any) -> bool:
        if isinstance(left, (int, float)) and isinstance(right, str):
            try:
                return left == self._to_num(right)
            except RuntimeExecError:
                return False
        if isinstance(right, (int, float)) and isinstance(left, str):
            try:
                return right == self._to_num(left)
            except RuntimeExecError:
                return False
        return left == right

    def _auto_cast(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        text = value.strip()
        lower = text.lower()
        if lower == "tru" or lower == "true":
            return True
        if lower == "fal" or lower == "false":
            return False
        if lower == "nul" or lower == "null":
            return None
        if re.fullmatch(r"[+-]?[0-9]+", text):
            try:
                return int(text)
            except ValueError:
                return text
        if re.fullmatch(r"[+-]?[0-9]+\.[0-9]+", text):
            try:
                return float(text)
            except ValueError:
                return text
        return value

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, RstValue):
            if value.kind == "ok":
                return {"ok": True, "data": self._json_safe(value.value)}
            return {"ok": False, "error": self._json_safe(value.value)}
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            return [self._json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [self._json_safe(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        return str(value)


class _AsyncThunk:
    def __init__(self, fn) -> None:
        self._fn = fn
        self._resolved = False
        self._value: Any = None

    def run(self) -> Any:
        if not self._resolved:
            self._value = self._fn()
            self._resolved = True
        return self._value


class NovaHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: Tuple[str, int], runtime: NovaRuntime) -> None:
        super().__init__(server_address, NovaRequestHandler)
        self.runtime = runtime


class NovaRequestHandler(BaseHTTPRequestHandler):
    server_version = "nova-http/0.1"

    def do_GET(self) -> None:
        self._handle_http()

    def do_POST(self) -> None:
        self._handle_http()

    def do_PUT(self) -> None:
        self._handle_http()

    def do_PATCH(self) -> None:
        self._handle_http()

    def do_DELETE(self) -> None:
        self._handle_http()

    def _handle_http(self) -> None:
        method = self.command.upper()
        headers = {k.lower(): v for k, v in self.headers.items()}
        content_type = headers.get("content-type", "").lower()

        body: Any = None
        content_length = self.headers.get("Content-Length")
        if content_length:
            raw = self.rfile.read(int(content_length))
            if raw:
                if "text/toon" in content_type:
                    try:
                        body = decode_toon(raw.decode("utf-8"))
                    except ToonDecodeError as exc:
                        status, payload = self.server.runtime._error_payload(
                            "BAD_REQUEST",
                            f"invalid TOON body: {exc}",
                            status=400,
                            fmt="json",
                        )
                        self._send_json(status, payload)
                        return
                else:
                    try:
                        body = json.loads(raw.decode("utf-8"))
                    except Exception:
                        status, payload = self.server.runtime._error_payload("BAD_REQUEST", "invalid JSON body", status=400, fmt="json")
                        self._send_json(status, payload)
                        return

        result = self.server.runtime.dispatch_http(method, self.path, headers, body)
        if result.fmt == "toon":
            self._send_toon(result.status, result.payload)
        else:
            self._send_json(result.status, result.payload)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_toon(self, status: int, payload: Any) -> None:
        encoded = encode_toon(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/toon; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(
    file_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8080,
    capabilities: Optional[List[str] | set[str] | tuple[str, ...]] = None,
) -> NovaHTTPServer:
    runtime = NovaRuntime.from_file(file_path, capabilities=capabilities)
    server = NovaHTTPServer((host, port), runtime)
    return server
