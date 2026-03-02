from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


class DbIrError(ValueError):
    pass


@dataclass
class DbIr:
    table_expr: Dict[str, Any]
    op: str = "q"
    where_expr: Optional[Dict[str, Any]] = None
    limit_expr: Optional[Dict[str, Any]] = None
    order_field_expr: Optional[Dict[str, Any]] = None
    order_direction_expr: Optional[Dict[str, Any]] = None


@dataclass
class DbPlan:
    table: str
    op: str
    where_expr: Optional[Dict[str, Any]] = None
    limit: Optional[int] = None
    order_field: Optional[str] = None
    order_direction: str = "asc"


def build_ir_from_table_stmt(stmt: Dict[str, Any]) -> DbIr:
    if stmt.get("type") != "TableStmt":
        raise DbIrError("build_ir_from_table_stmt expects TableStmt")

    op = stmt.get("op") or "q"
    if op not in {"get", "q"}:
        raise DbIrError(f"unsupported tb op '{op}'")

    ir = DbIr(table_expr=stmt["table"], op=op)
    for clause in stmt.get("query", []):
        apply_clause(ir, clause)
    return ir


def apply_clause(ir: DbIr, clause: Dict[str, Any]) -> None:
    ctype = clause.get("type")
    if ctype == "WhereStmt":
        ir.where_expr = clause["condition"]
        return
    if ctype == "LimitStmt":
        ir.limit_expr = clause["value"]
        return
    if ctype == "OrderStmt":
        ir.order_field_expr = clause["field"]
        ir.order_direction_expr = clause["direction"]
        return
    raise DbIrError(f"unsupported DB clause type '{ctype}'")


def compile_plan(
    ir: DbIr,
    *,
    eval_table_name: Callable[[Dict[str, Any]], str],
    eval_expr: Callable[[Dict[str, Any]], Any],
) -> DbPlan:
    table = eval_table_name(ir.table_expr)
    if not table:
        raise DbIrError("db plan requires non-empty table")

    limit: Optional[int] = None
    if ir.limit_expr is not None:
        limit_value = eval_expr(ir.limit_expr)
        try:
            limit = int(limit_value)
        except Exception as exc:
            raise DbIrError(f"lim expects integer-like value, got {limit_value!r}") from exc
        if limit < 0:
            raise DbIrError("lim must be >= 0")

    order_field: Optional[str] = None
    order_direction = "asc"
    if ir.order_field_expr is not None:
        order_field = str(eval_expr(ir.order_field_expr))
    if ir.order_direction_expr is not None:
        order_direction = str(eval_expr(ir.order_direction_expr)).lower()
        if order_direction not in {"asc", "desc"}:
            raise DbIrError("ord direction must be asc or desc")

    return DbPlan(
        table=table,
        op=ir.op,
        where_expr=ir.where_expr,
        limit=limit,
        order_field=order_field,
        order_direction=order_direction,
    )


def plan_to_dict(plan: DbPlan) -> Dict[str, Any]:
    return {
        "table": plan.table,
        "op": plan.op,
        "where": plan.where_expr,
        "limit": plan.limit,
        "order": {
            "field": plan.order_field,
            "direction": plan.order_direction,
        },
    }


class InMemoryDbIrAdapter:
    def __init__(self) -> None:
        self.tables: Dict[str, List[Dict[str, Any]]] = {}
        self.next_ids: Dict[str, int] = {}

    def read(self, plan: DbPlan, row_matches: Callable[[Dict[str, Any], Optional[Dict[str, Any]]], bool]) -> List[Dict[str, Any]]:
        rows = [dict(row) for row in self._rows_for(plan.table)]
        rows = [row for row in rows if row_matches(row, plan.where_expr)]

        if plan.order_field is not None:
            reverse = plan.order_direction == "desc"
            rows = sorted(rows, key=lambda row: row.get(plan.order_field), reverse=reverse)

        if plan.limit is not None:
            rows = rows[: plan.limit]
        return rows

    def create(self, plan: DbPlan, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise DbIrError("db.create expects object payload")
        table = plan.table
        row = dict(payload)
        if "id" not in row:
            row["id"] = self._next_id(table)
        self.tables.setdefault(table, []).append(row)
        return dict(row)

    def update(
        self,
        plan: DbPlan,
        payload: Any,
        row_matches: Callable[[Dict[str, Any], Optional[Dict[str, Any]]], bool],
    ) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise DbIrError("db.update expects object payload")
        rows = self.tables.setdefault(plan.table, [])
        updated: List[Dict[str, Any]] = []
        for row in rows:
            if row_matches(row, plan.where_expr):
                row.update(payload)
                updated.append(dict(row))
        return {"updated": updated, "count": len(updated)}

    def delete(
        self,
        plan: DbPlan,
        row_matches: Callable[[Dict[str, Any], Optional[Dict[str, Any]]], bool],
    ) -> Dict[str, Any]:
        rows = self.tables.setdefault(plan.table, [])
        kept: List[Dict[str, Any]] = []
        deleted = 0
        for row in rows:
            if row_matches(row, plan.where_expr):
                deleted += 1
            else:
                kept.append(row)
        self.tables[plan.table] = kept
        return {"deleted": deleted}

    def _rows_for(self, table: str) -> List[Dict[str, Any]]:
        return self.tables.setdefault(table, [])

    def _next_id(self, table: str) -> int:
        value = self.next_ids.get(table, 1)
        self.next_ids[table] = value + 1
        return value
