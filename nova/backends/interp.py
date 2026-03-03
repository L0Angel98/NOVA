from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, Set, Tuple

from nova.cap import DbSqliteCap, DbSqliteError, HttpCapError, html_sct, html_tte, http_get
from nova.ir.nodes import (
    IrArr,
    IrCall,
    IrCap,
    IrExpr,
    IrGrd,
    IrId,
    IrJson,
    IrLet,
    IrMdl,
    IrObj,
    IrRstErr,
    IrRstOk,
    IrStmt,
)

from .base import BackendBuildResult, BackendError


class InterpBackend:
    name = "interp"

    def build(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> BackendBuildResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        artifact = out_dir / f"{src_path.stem}.ir.json"
        if artifact.resolve() != ir_path.resolve():
            shutil.copyfile(ir_path, artifact)
        return BackendBuildResult(backend=self.name, ir_path=ir_path, artifact=artifact)

    def run(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> int:
        vm = _IrVm(caps)
        try:
            ok, value = vm.exec(ir)
        finally:
            vm.close()

        if ok:
            sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
            return 0

        sys.stderr.write(json.dumps({"code": "RUNTIME_ERR", "msg": value}, ensure_ascii=False) + "\n")
        return 1


class _IrVm:
    def __init__(self, caps: Set[str]) -> None:
        self.caps = set(caps)
        self.env: Dict[str, Any] = {}
        self.db = DbSqliteCap()

    def close(self) -> None:
        self.db.close_all()

    def exec(self, ir: IrMdl) -> Tuple[bool, Any]:
        body = ir.b
        if not body and ir.rte:
            raise BackendError("interp run supports script subset only (use 'nova serve' for rte apps)")

        last: Any = None
        for stmt in body:
            kind = stmt.k
            if kind == "let":
                s = stmt if isinstance(stmt, IrLet) else None
                if s is None:
                    raise BackendError("invalid let node")
                self.env[s.n] = self._eval_expr(s.v)
                continue
            if kind == "cap":
                _ = stmt if isinstance(stmt, IrCap) else None
                continue
            if kind == "grd":
                s = stmt if isinstance(stmt, IrGrd) else None
                if s is None:
                    raise BackendError("invalid grd node")
                code = str(self._eval_expr(s.c))
                for target in s.t:
                    value = self._eval_expr(target)
                    if not self._guard_value_present(value):
                        return False, {"code": code, "msg": f"missing required value: {self._expr_label(target)}"}
                continue
            if kind == "call":
                s = stmt if isinstance(stmt, IrCall) else None
                if s is None:
                    raise BackendError("invalid call node")
                last = self._call(s.fn, [self._eval_expr(arg) for arg in s.a])
                continue
            if kind == "rst.ok":
                s = stmt if isinstance(stmt, IrRstOk) else None
                if s is None:
                    raise BackendError("invalid rst.ok node")
                return True, self._eval_expr(s.v)
            if kind == "rst.err":
                s = stmt if isinstance(stmt, IrRstErr) else None
                if s is None:
                    raise BackendError("invalid rst.err node")
                return False, self._eval_expr(s.v)
            raise BackendError(f"unsupported IR stmt kind '{kind}'")
        return True, last

    def _eval_expr(self, expr: IrExpr) -> Any:
        kind = expr.k
        if kind == "json":
            e = expr if isinstance(expr, IrJson) else None
            if e is None:
                raise BackendError("invalid json node")
            return e.v
        if kind == "id":
            e = expr if isinstance(expr, IrId) else None
            if e is None:
                raise BackendError("invalid id node")
            return self._read_id(e.n)
        if kind == "obj":
            e = expr if isinstance(expr, IrObj) else None
            if e is None:
                raise BackendError("invalid obj node")
            return {key: self._eval_expr(value) for key, value in e.f.items()}
        if kind == "arr":
            e = expr if isinstance(expr, IrArr) else None
            if e is None:
                raise BackendError("invalid arr node")
            return [self._eval_expr(value) for value in e.i]
        if kind == "call":
            e = expr if isinstance(expr, IrCall) else None
            if e is None:
                raise BackendError("invalid call node")
            return self._call(e.fn, [self._eval_expr(arg) for arg in e.a])
        raise BackendError(f"unsupported IR expr kind '{kind}'")

    def _read_id(self, name: str) -> Any:
        parts = [part for part in name.split(".") if part != ""]
        if not parts:
            return None

        if parts[0] in self.env:
            value = self.env[parts[0]]
            for part in parts[1:]:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = getattr(value, part, None)
            return value

        if name == "nul":
            return None
        if name == "tru":
            return True
        if name == "fal":
            return False
        return None

    def _guard_value_present(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True

    def _expr_label(self, expr: IrExpr) -> str:
        if isinstance(expr, IrId):
            return expr.n
        return "<expr>"

    def _require_cap(self, cap: str, op: str) -> None:
        if cap not in self.caps:
            raise BackendError(f"{op} requires --cap {cap}")

    def _call(self, fn: str, args: list[Any]) -> Any:
        if fn == "print":
            value = args[0] if args else None
            sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
            return value

        if fn in {"http.get", "net.get"}:
            self._require_cap("net", fn)
            try:
                url = args[0] if len(args) > 0 else ""
                headers = args[1] if len(args) > 1 else None
                timeout = args[2] if len(args) > 2 else None
                return http_get(url, headers, timeout)
            except HttpCapError as exc:
                raise BackendError(str(exc)) from exc

        if fn == "html.tte":
            self._require_cap("html", fn)
            value = args[0] if args else ""
            return html_tte(value)

        if fn == "html.sct":
            self._require_cap("html", fn)
            html = args[0] if len(args) > 0 else ""
            css = args[1] if len(args) > 1 else ""
            return html_sct(html, css)

        if fn == "db.opn":
            self._require_cap("db", fn)
            path = args[0] if args else ""
            try:
                return self.db.opn(path)
            except DbSqliteError as exc:
                raise BackendError(str(exc)) from exc

        if fn == "db.qry":
            self._require_cap("db", fn)
            handle = args[0] if len(args) > 0 else ""
            sql = args[1] if len(args) > 1 else ""
            params = args[2] if len(args) > 2 else None
            try:
                return self.db.qry(handle, sql, params)
            except DbSqliteError as exc:
                raise BackendError(str(exc)) from exc

        if fn == "db.cls":
            self._require_cap("db", fn)
            handle = args[0] if args else ""
            try:
                return self.db.cls(handle)
            except DbSqliteError as exc:
                raise BackendError(str(exc)) from exc

        raise BackendError(f"unsupported IR call '{fn}'")
