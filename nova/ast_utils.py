from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List

DIRECTION_ALIASES = {
    "ascending": "asc",
    "descending": "desc",
    "asc": "asc",
    "desc": "desc",
    "ASC": "asc",
    "DESC": "desc",
}


def canonicalize_ast(node: Any) -> Any:
    if isinstance(node, list):
        return [canonicalize_ast(item) for item in node]

    if not isinstance(node, dict):
        return node

    typ = node.get("type")

    if typ == "ParenExpr":
        return canonicalize_ast(node["expression"])

    if typ == "NumberLiteral":
        return {
            "type": "NumberLiteral",
            "value": normalize_number(str(node["value"])),
        }

    if typ == "ObjectField":
        return {
            "type": "ObjectField",
            "key": node["key"],
            "value": canonicalize_ast(node["value"]),
        }

    if typ == "ObjectLiteral":
        fields = [canonicalize_ast(field) for field in node.get("fields", [])]
        fields = sorted(fields, key=lambda item: item["key"])
        return {"type": "ObjectLiteral", "fields": fields}

    if typ == "CapStmt":
        value = canonicalize_ast(node["value"])
        if isinstance(value, dict) and value.get("type") == "ArrayLiteral":
            value = {
                "type": "ArrayLiteral",
                "items": sorted(
                    value.get("items", []),
                    key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
                ),
            }
        return {"type": "CapStmt", "value": value}

    if typ == "OrderStmt":
        direction = canonicalize_ast(node["direction"])
        if isinstance(direction, dict):
            if direction.get("type") == "Identifier":
                mapped = DIRECTION_ALIASES.get(direction["name"])
                if mapped:
                    direction = {"type": "Identifier", "name": mapped}
            elif direction.get("type") == "StringLiteral":
                mapped = DIRECTION_ALIASES.get(direction["value"])
                if mapped:
                    direction = {"type": "Identifier", "name": mapped}

        return {
            "type": "OrderStmt",
            "field": canonicalize_ast(node["field"]),
            "direction": direction,
        }

    normalized: Dict[str, Any] = {"type": typ} if typ is not None else {}
    for key, value in node.items():
        if key == "type":
            continue
        normalized[key] = canonicalize_ast(value)
    return normalized


def normalize_number(raw: str) -> str:
    text = raw.strip()
    if not text:
        return "0"

    sign = ""
    if text[0] in "+-":
        sign = "-" if text[0] == "-" else ""
        text = text[1:]

    if "." in text:
        int_part, frac_part = text.split(".", 1)
        int_part = int_part.lstrip("0") or "0"
        frac_part = frac_part.rstrip("0")
        if frac_part:
            normalized = f"{int_part}.{frac_part}"
        else:
            normalized = int_part
    else:
        normalized = text.lstrip("0") or "0"

    if normalized == "0":
        return "0"

    return f"{sign}{normalized}"


def ast_to_json(ast: Dict[str, Any], *, indent: int = 2) -> str:
    return json.dumps(ast, indent=indent, ensure_ascii=False, sort_keys=True)
