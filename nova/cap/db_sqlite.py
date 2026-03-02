from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class DbSqliteError(Exception):
    code: str
    msg: str

    def __str__(self) -> str:
        return f"{self.code}: {self.msg}"


class DbSqliteCap:
    def __init__(self) -> None:
        self._seq = 0
        self._handles: Dict[str, sqlite3.Connection] = {}

    def opn(self, path: Any) -> str:
        db_path = str(path).strip()
        if db_path == "":
            raise DbSqliteError("DB_INPUT", "db.opn requires path")
        target = Path(db_path)
        if target.parent and str(target.parent) != "":
            target.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(str(target))
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise DbSqliteError("DB_OPEN", str(exc)) from exc
        self._seq += 1
        handle = f"h{self._seq}"
        self._handles[handle] = conn
        return handle

    def qry(self, handle: Any, sql: Any, args: Any = None) -> Any:
        hid = str(handle).strip()
        if hid == "":
            raise DbSqliteError("DB_INPUT", "db.qry requires handle id")
        conn = self._handles.get(hid)
        if conn is None:
            raise DbSqliteError("DB_HANDLE", f"unknown db handle '{hid}'")

        text = str(sql)
        if text.strip() == "":
            raise DbSqliteError("DB_INPUT", "db.qry requires sql")

        params = _normalize_args(args)
        try:
            cur = conn.cursor()
            cur.execute(text, params)
        except sqlite3.Error as exc:
            raise DbSqliteError("DB_QRY", str(exc)) from exc

        if cur.description is None:
            conn.commit()
            count = 0 if cur.rowcount is None or cur.rowcount < 0 else int(cur.rowcount)
            return {"cnt": count}

        rows = cur.fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append({str(key): row[key] for key in row.keys()})
        return out

    def cls(self, handle: Any) -> bool:
        hid = str(handle).strip()
        conn = self._handles.pop(hid, None)
        if conn is None:
            raise DbSqliteError("DB_HANDLE", f"unknown db handle '{hid}'")
        try:
            conn.close()
        except sqlite3.Error as exc:
            raise DbSqliteError("DB_CLOSE", str(exc)) from exc
        return True

    def close_all(self) -> None:
        for handle in list(self._handles.keys()):
            conn = self._handles.pop(handle)
            try:
                conn.close()
            except sqlite3.Error:
                continue


def _normalize_args(args: Any) -> List[Any] | Dict[str, Any]:
    if args is None:
        return []
    if isinstance(args, (list, tuple)):
        return list(args)
    if isinstance(args, dict):
        return {str(key): value for key, value in args.items()}
    raise DbSqliteError("DB_INPUT", "db.qry args must be list/tuple/object")

