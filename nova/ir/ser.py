from __future__ import annotations

import dataclasses
import json
from typing import Any


def ir_to_obj(node: Any) -> Any:
    if dataclasses.is_dataclass(node):
        out = {}
        for field in dataclasses.fields(node):
            out[field.name] = ir_to_obj(getattr(node, field.name))
        return out
    if isinstance(node, list):
        return [ir_to_obj(item) for item in node]
    if isinstance(node, tuple):
        return [ir_to_obj(item) for item in node]
    if isinstance(node, dict):
        return {str(key): ir_to_obj(value) for key, value in node.items()}
    return node


def ir_to_json(node: Any, *, indent: int = 2) -> str:
    return json.dumps(ir_to_obj(node), indent=indent, ensure_ascii=False, sort_keys=True)

