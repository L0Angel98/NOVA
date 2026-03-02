from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .nodes import IrArr, IrCall, IrCap, IrExpr, IrId, IrJson, IrLet, IrMdl, IrObj, IrRstErr, IrRstOk, IrRte, IrStmt


class IrEmitError(ValueError):
    pass


def emit_ir(ast: Dict[str, Any], *, source_path: str | Path = "main.nv") -> IrMdl:
    if ast.get("type") != "Program":
        raise IrEmitError("AST root must be Program")

    module = _first_module(ast.get("body", []))
    if module is not None:
        name = module.get("name") or _stem_name(source_path)
        version = module.get("version") or "0.1.4"
        body = module.get("body", [])
    else:
        name = _stem_name(source_path)
        version = "0.1.4"
        body = ast.get("body", [])

    routes: List[IrRte] = []
    script_body: List[IrStmt] = []

    for stmt in body:
        node = _unwrap_public(stmt)
        typ = node.get("type")
        if typ == "RouteDecl":
            routes.append(_emit_route(node))
            continue

        emitted = _emit_stmt(node, allow_cap_stmt=True)
        if emitted is not None:
            script_body.append(emitted)

    return IrMdl(irv="0.1.4", n=name, v=version, rte=routes, b=script_body)


def _first_module(body: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    for stmt in body:
        node = _unwrap_public(stmt)
        if node.get("type") == "ModuleDecl":
            return node
    return None


def _stem_name(source_path: str | Path) -> str:
    stem = Path(str(source_path)).stem
    return stem if stem else "main"


def _unwrap_public(stmt: Dict[str, Any]) -> Dict[str, Any]:
    if stmt.get("type") == "PublicDecl":
        return stmt["declaration"]
    return stmt


def _emit_route(stmt: Dict[str, Any]) -> IrRte:
    method = _route_method(stmt.get("method"))
    path = _expect_static_string(stmt.get("path"), "rte path")
    fmt = _route_format(stmt.get("format"))
    body: List[IrStmt] = []
    for inner in stmt.get("body", []):
        emitted = _emit_stmt(inner, allow_cap_stmt=True)
        if emitted is not None:
            body.append(emitted)
    return IrRte(m=method, p=path, f=fmt, b=body)


def _emit_stmt(stmt: Dict[str, Any], *, allow_cap_stmt: bool) -> IrStmt | None:
    typ = stmt.get("type")
    if typ == "LetStmt":
        return IrLet(n=str(stmt["name"]), v=_emit_expr(stmt["value"]))
    if typ == "ExprStmt":
        expr = stmt["expression"]
        if _is_rst_call(expr, "ok"):
            return IrRstOk(v=_emit_expr(expr.get("args", [])[0] if expr.get("args") else {"type": "NullLiteral"}))
        if _is_rst_call(expr, "err"):
            return IrRstErr(v=_emit_expr(expr.get("args", [])[0] if expr.get("args") else {"type": "NullLiteral"}))
        if expr.get("type") == "CallExpr":
            return _emit_expr(expr)  # type: ignore[return-value]
        raise IrEmitError(f"unsupported ExprStmt expression '{expr.get('type')}' for IR")
    if typ == "ErrorStmt":
        return IrRstErr(v=_emit_expr(stmt["value"]))
    if typ == "CapStmt" and allow_cap_stmt:
        return IrCap(c=_emit_caps(stmt.get("value")))
    raise IrEmitError(f"unsupported statement type '{typ}' for IR")


def _emit_expr(expr: Dict[str, Any]) -> IrExpr:
    typ = expr.get("type")
    if typ == "CapExpr":
        return _emit_expr(expr["expression"])
    if typ == "StringLiteral":
        return IrJson(v=str(expr["value"]))
    if typ == "NumberLiteral":
        raw = str(expr["value"])
        if "." in raw:
            try:
                return IrJson(v=float(raw))
            except ValueError:
                pass
        try:
            return IrJson(v=int(raw))
        except ValueError:
            return IrJson(v=raw)
    if typ == "BooleanLiteral":
        return IrJson(v=bool(expr["value"]))
    if typ == "NullLiteral":
        return IrJson(v=None)
    if typ == "Identifier":
        return IrId(n=str(expr["name"]))
    if typ == "ObjectLiteral":
        fields = {str(field["key"]): _emit_expr(field["value"]) for field in expr.get("fields", [])}
        return IrObj(f=fields)
    if typ == "ArrayLiteral":
        return IrArr(i=[_emit_expr(item) for item in expr.get("items", [])])
    if typ == "CallExpr":
        return IrCall(fn=_expr_to_fn(expr["callee"]), a=[_emit_expr(item) for item in expr.get("args", [])])
    if typ == "MemberExpr":
        return IrId(n=_expr_to_fn(expr))
    raise IrEmitError(f"unsupported expression type '{typ}' for IR")


def _is_rst_call(expr: Dict[str, Any], prop: str) -> bool:
    if expr.get("type") != "CallExpr":
        return False
    callee = expr.get("callee", {})
    return (
        isinstance(callee, dict)
        and callee.get("type") == "MemberExpr"
        and isinstance(callee.get("object"), dict)
        and callee["object"].get("type") == "Identifier"
        and callee["object"].get("name") == "rst"
        and callee.get("property") == prop
    )


def _expr_to_fn(expr: Dict[str, Any]) -> str:
    typ = expr.get("type")
    if typ == "Identifier":
        return str(expr["name"])
    if typ == "MemberExpr":
        left = _expr_to_fn(expr["object"])
        return f"{left}.{expr['property']}"
    raise IrEmitError(f"call target must be identifier/member chain, got '{typ}'")


def _expect_static_string(expr: Dict[str, Any] | None, label: str) -> str:
    if not isinstance(expr, dict):
        raise IrEmitError(f"{label} must be static string")
    if expr.get("type") == "StringLiteral":
        return str(expr["value"])
    if expr.get("type") == "Identifier":
        return str(expr["name"])
    raise IrEmitError(f"{label} must be static string")


def _route_method(expr: Dict[str, Any] | None) -> str:
    method = _expect_static_string(expr, "rte method").upper()
    aliases = {"DEL": "DELETE", "PAT": "PATCH", "HED": "HEAD", "OPT": "OPTIONS"}
    return aliases.get(method, method)


def _route_format(expr: Dict[str, Any] | None) -> str:
    fmt = _expect_static_string(expr, "rte format").lower()
    if fmt not in {"json", "toon"}:
        raise IrEmitError("rte format must be json|toon")
    return fmt


def _emit_caps(expr: Dict[str, Any] | None) -> List[str]:
    if not isinstance(expr, dict):
        return []
    typ = expr.get("type")
    if typ == "ArrayLiteral":
        out: List[str] = []
        for item in expr.get("items", []):
            out.extend(_emit_caps(item))
        return sorted({item for item in out if item != ""})
    if typ == "Identifier":
        return [str(expr.get("name", "")).strip()]
    if typ == "StringLiteral":
        return [str(expr.get("value", "")).strip()]
    return []
