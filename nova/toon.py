from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple


TOON_VERSION_LINE = "@toon v1"
TOON_TABLE_LINE = "@type table"
TOON_JSON_LINE = "@type json"
TOON_STD_LINE = "@type std"
TOON_ARRAY_LINE = "@type array"
TOON_ERROR_LINE = "@type error"

HEADER_PATTERN = re.compile(r"^(?P<name>[^\[\]]+?)(?:\[(?P<len>[0-9]+)\])?$")
INT_PATTERN = re.compile(r"^[+-]?[0-9]+$")
FLOAT_PATTERN = re.compile(r"^[+-]?[0-9]+\.[0-9]+$")


class ToonError(ValueError):
    pass


class ToonEncodeError(ToonError):
    pass


class ToonDecodeError(ToonError):
    pass


def encode_toon(value: Any) -> str:
    """Encode JSON-compatible data into canonical TOON v1 text.

    Canonical modes:
    - Table mode for list[object] with rectangular keys.
    - JSON mode fallback for any other JSON-like value.
    """
    if _is_tabular_array(value):
        return _encode_table(value)
    return _encode_json_fallback(value)


def decode_toon(text: str) -> Any:
    """Decode canonical TOON v1 text back to JSON-compatible data."""
    lines = _normalize_lines(text)
    if not lines:
        raise ToonDecodeError("empty TOON payload")
    if lines[0] != TOON_VERSION_LINE:
        raise ToonDecodeError("missing or invalid TOON version header")

    if len(lines) < 2:
        raise ToonDecodeError("missing TOON type header")

    mode = lines[1]
    if mode == TOON_TABLE_LINE:
        return _decode_table(lines[2:])
    if mode == TOON_JSON_LINE:
        return _decode_json_fallback(lines[2:])
    if mode == TOON_ARRAY_LINE:
        return _decode_array(lines[2:])
    if mode == TOON_STD_LINE:
        return _decode_standard(lines[2:])
    if mode == TOON_ERROR_LINE:
        return _decode_error(lines[2:])

    raise ToonDecodeError(f"unsupported TOON type header: {mode}")


def toon_size_bytes(value: Any) -> int:
    return len(encode_toon(value).encode("utf-8"))


def json_size_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _is_tabular_array(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    if not value:
        return True
    if not all(isinstance(item, dict) for item in value):
        return False

    keys = list(value[0].keys())
    for item in value[1:]:
        if list(item.keys()) != keys:
            return False
    return True


def _encode_table(rows: List[Dict[str, Any]]) -> str:
    lines = [TOON_VERSION_LINE, TOON_TABLE_LINE]
    lines.append(f"@rows {len(rows)}")

    if not rows:
        lines.append("|_|")
        return "\n".join(lines) + "\n"

    columns = list(rows[0].keys())
    lengths = _infer_array_lengths(rows, columns)
    header_cells = []
    for col in columns:
        expected_len = lengths.get(col)
        if expected_len is not None:
            header_cells.append(f"{col}[{expected_len}]")
        else:
            header_cells.append(col)
    lines.append(_make_pipe_line(header_cells))

    for row in rows:
        cells = []
        for col in columns:
            cells.append(_encode_cell(row.get(col)))
        lines.append(_make_pipe_line(cells))

    return "\n".join(lines) + "\n"


def _encode_json_fallback(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError as exc:
        raise ToonEncodeError(f"value is not JSON-serializable: {exc}") from exc

    return f"{TOON_VERSION_LINE}\n{TOON_JSON_LINE}\n{encoded}\n"


def _decode_table(lines: List[str]) -> Any:
    if not lines:
        raise ToonDecodeError("table payload is incomplete")

    row_count = _parse_rows_header(lines[0])
    if len(lines) < 2:
        raise ToonDecodeError("table payload missing header line")

    header_cells = _parse_pipe_line(lines[1])
    if header_cells == ["_"]:
        if row_count != 0:
            raise ToonDecodeError("@rows does not match empty table marker")
        if len(lines) != 2:
            raise ToonDecodeError("empty table must not include data rows")
        return []

    columns: List[Tuple[str, int | None]] = []
    seen = set()
    for cell in header_cells:
        match = HEADER_PATTERN.match(cell)
        if not match:
            raise ToonDecodeError(f"invalid table header cell '{cell}'")
        name = match.group("name")
        if name in seen:
            raise ToonDecodeError(f"duplicate table header column '{name}'")
        seen.add(name)
        expected_len = match.group("len")
        columns.append((name, int(expected_len) if expected_len is not None else None))

    data_lines = lines[2:]
    if len(data_lines) != row_count:
        raise ToonDecodeError(f"@rows={row_count} but found {len(data_lines)} data rows")

    rows: List[Dict[str, Any]] = []
    for ridx, line in enumerate(data_lines):
        cells = _parse_pipe_line(line)
        if len(cells) != len(columns):
            raise ToonDecodeError(
                f"row {ridx} has {len(cells)} cells, expected {len(columns)}"
            )

        row: Dict[str, Any] = {}
        for cidx, raw_cell in enumerate(cells):
            name, expected_len = columns[cidx]
            value = _decode_cell(raw_cell)
            if expected_len is not None and value is not None:
                if not isinstance(value, list):
                    raise ToonDecodeError(
                        f"column '{name}' requires array[{expected_len}] but got {type(value).__name__}"
                    )
                if len(value) != expected_len:
                    raise ToonDecodeError(
                        f"column '{name}' requires array[{expected_len}] but got length {len(value)}"
                    )
            row[name] = value
        rows.append(row)

    return rows


def _decode_json_fallback(lines: List[str]) -> Any:
    if not lines:
        raise ToonDecodeError("json TOON payload is empty")
    text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToonDecodeError(f"invalid json payload in TOON: {exc}") from exc


def _decode_standard(lines: List[str]) -> Any:
    if not lines:
        return {}

    # Compact std variant:
    # @toon v1
    # @type std
    # |k|v|
    # |"a"|1|
    if lines[0].lstrip().startswith("|"):
        header = _parse_pipe_line(lines[0].strip())
        rows: List[Dict[str, Any]] = []
        for ridx, raw in enumerate(lines[1:]):
            stripped = raw.strip()
            if stripped == "":
                continue
            if not stripped.startswith("|"):
                raise ToonDecodeError(f"invalid std compact line {ridx + 2}: expected table row")
            cells = _parse_pipe_line(stripped)
            if len(cells) != len(header):
                raise ToonDecodeError(
                    f"std compact row {ridx} has {len(cells)} cells, expected {len(header)}"
                )
            row: Dict[str, Any] = {}
            for cidx, col in enumerate(header):
                row[col] = _decode_cell(cells[cidx])
            rows.append(row)
        return _materialize_standard_table(header, rows)

    entries = _parse_standard_entries(lines)
    if not entries:
        return {}

    root = _parse_standard_tree(entries)
    return _materialize_standard_root(root)


def _decode_array(lines: List[str]) -> Any:
    if not lines:
        return []

    idx = 0
    if lines[0].startswith("@rows "):
        idx = 1
    if idx >= len(lines):
        return []

    header = _parse_pipe_line(lines[idx].strip())
    if header == ["_"]:
        return []

    rows: List[Dict[str, Any]] = []
    for ridx, raw in enumerate(lines[idx + 1 :]):
        stripped = raw.strip()
        if stripped == "":
            continue
        if not stripped.startswith("|"):
            raise ToonDecodeError(f"invalid array row at line {ridx + idx + 2}")
        cells = _parse_pipe_line(stripped)
        if len(cells) != len(header):
            raise ToonDecodeError(
                f"array row {ridx} has {len(cells)} cells, expected {len(header)}"
            )
        row: Dict[str, Any] = {}
        for cidx, col in enumerate(header):
            row[col] = _decode_cell(cells[cidx])
        rows.append(row)
    return rows


def _decode_error(lines: List[str]) -> Any:
    data = _decode_array(lines)
    if isinstance(data, list):
        if all(isinstance(row, dict) and set(row.keys()) == {"k", "v"} for row in data):
            out: Dict[str, Any] = {}
            for row in data:
                out[str(row.get("k", ""))] = row.get("v")
            return out
        return {"rows": data}
    return data


def _parse_standard_entries(lines: List[str]) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for idx, raw in enumerate(lines):
        if raw.strip() == "":
            continue
        indent_spaces = len(raw) - len(raw.lstrip(" "))
        if indent_spaces % 2 != 0:
            raise ToonDecodeError(f"invalid indentation at standard line {idx + 1}: use 2-space steps")
        out.append((indent_spaces // 2, raw.strip()))
    return out


def _parse_standard_tree(entries: List[Tuple[int, str]]) -> Dict[str, Any]:
    root: Dict[str, Any] = {"name": "__root__", "table": None, "children": []}
    stack: List[Tuple[int, Dict[str, Any]]] = [(-1, root)]

    i = 0
    while i < len(entries):
        depth, content = entries[i]
        while stack and stack[-1][0] >= depth:
            stack.pop()
        if not stack:
            raise ToonDecodeError("invalid standard TOON nesting")

        if not content.endswith(":"):
            raise ToonDecodeError(f"expected '<block>:' at standard line {i + 1}, got '{content}'")

        name = content[:-1].strip()
        if name == "":
            raise ToonDecodeError(f"empty block name at standard line {i + 1}")

        node: Dict[str, Any] = {"name": name, "table": None, "children": []}
        stack[-1][1]["children"].append(node)

        j = i + 1
        if j < len(entries) and entries[j][0] == depth + 1 and entries[j][1].startswith("|"):
            header_cells = _parse_pipe_line(entries[j][1])
            j += 1

            rows: List[Dict[str, Any]] = []
            while j < len(entries) and entries[j][0] == depth + 1 and entries[j][1].startswith("|"):
                cells = _parse_pipe_line(entries[j][1])
                if len(cells) != len(header_cells):
                    raise ToonDecodeError(
                        f"standard row at line {j + 1} has {len(cells)} cells, expected {len(header_cells)}"
                    )
                row: Dict[str, Any] = {}
                for cidx, col in enumerate(header_cells):
                    row[col] = _decode_cell(cells[cidx])
                rows.append(row)
                j += 1
            node["table"] = {"header": header_cells, "rows": rows}

        stack.append((depth, node))
        i = j

    return root


def _materialize_standard_root(root: Dict[str, Any]) -> Any:
    out: Dict[str, Any] = {}
    for child in root["children"]:
        key = _normalize_standard_key(str(child["name"]))
        if key in out:
            raise ToonDecodeError(f"duplicate top-level standard block '{key}'")
        out[key] = _materialize_standard_node(child)

    root_obj = out.pop("root", None)
    if isinstance(root_obj, dict):
        merged = dict(root_obj)
        for key, value in out.items():
            merged[key] = value
        return merged
    if root_obj is not None:
        out["root"] = root_obj
    return out


def _materialize_standard_node(node: Dict[str, Any]) -> Any:
    table = node.get("table")
    children = node.get("children", [])

    if table is None:
        base: Any = {}
    else:
        base = _materialize_standard_table(table["header"], table["rows"])

    if not children:
        return base

    if isinstance(base, dict):
        out: Dict[str, Any] = dict(base)
    else:
        out = {"rows": base}

    for child in children:
        key = _normalize_standard_key(str(child["name"]))
        value = _materialize_standard_node(child)
        if key in out:
            raise ToonDecodeError(f"duplicate standard nested block '{key}'")
        out[key] = value
    return out


def _materialize_standard_table(header: List[str], rows: List[Dict[str, Any]]) -> Any:
    if header == ["k", "v"]:
        out: Dict[str, Any] = {}
        for row in rows:
            key = str(row.get("k", ""))
            if key == "":
                raise ToonDecodeError("standard k/v table row with empty key")
            if key in out:
                raise ToonDecodeError(f"duplicate key '{key}' in standard k/v table")
            out[key] = row.get("v")
        return out

    if header and header[0] == "k" and len(header) > 2:
        out_obj: Dict[str, Any] = {}
        for row in rows:
            key = str(row.get("k", ""))
            if key == "":
                raise ToonDecodeError("standard keyed table row with empty key")
            if key in out_obj:
                raise ToonDecodeError(f"duplicate key '{key}' in standard keyed table")
            payload: Dict[str, Any] = {}
            for col in header[1:]:
                payload[col] = row.get(col)
            out_obj[key] = payload
        return out_obj

    if header == ["i", "v"]:
        return [item[1].get("v") for item in _sorted_index_rows(rows)]

    if header and header[0] == "i":
        out_rows: List[Dict[str, Any]] = []
        for _, row in _sorted_index_rows(rows):
            item = {k: v for k, v in row.items() if k != "i"}
            out_rows.append(item)
        return out_rows

    return rows


def _sorted_index_rows(rows: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    indexed: List[Tuple[int, Dict[str, Any]]] = []
    seen: set[int] = set()
    for row in rows:
        raw = row.get("i")
        if not isinstance(raw, int):
            raise ToonDecodeError("standard indexed table requires integer 'i' column")
        if raw in seen:
            raise ToonDecodeError(f"duplicate index '{raw}' in standard indexed table")
        seen.add(raw)
        indexed.append((raw, row))
    indexed.sort(key=lambda item: item[0])
    return indexed


def _normalize_standard_key(name: str) -> str:
    if name.startswith("#nova_"):
        return name[6:]
    return name


def _infer_array_lengths(rows: List[Dict[str, Any]], columns: List[str]) -> Dict[str, int]:
    lengths: Dict[str, int] = {}
    for col in columns:
        expected: int | None = None
        valid = True
        for row in rows:
            value = row.get(col)
            if value is None:
                continue
            if not isinstance(value, list):
                valid = False
                break
            if expected is None:
                expected = len(value)
            elif len(value) != expected:
                valid = False
                break
        if valid and expected is not None:
            lengths[col] = expected
    return lengths


def _make_pipe_line(cells: List[str]) -> str:
    return "|" + "|".join(cells) + "|"


def _encode_cell(value: Any) -> str:
    if value is None:
        return "nul"
    if isinstance(value, bool):
        return "tru" if value else "fal"
    if isinstance(value, (int, float)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError as exc:
        raise ToonEncodeError(f"cell value is not JSON-serializable: {exc}") from exc


def _decode_cell(raw: str) -> Any:
    token = raw.strip()
    if token == "nul":
        return None
    if token == "tru":
        return True
    if token == "fal":
        return False
    if INT_PATTERN.match(token):
        try:
            return int(token)
        except ValueError:
            pass
    if FLOAT_PATTERN.match(token):
        try:
            return float(token)
        except ValueError:
            pass

    try:
        return json.loads(token)
    except json.JSONDecodeError:
        # TOON std accepts bare tokens for compact scalar strings.
        return token


def _parse_rows_header(line: str) -> int:
    if not line.startswith("@rows "):
        raise ToonDecodeError("table payload missing '@rows N' header")
    raw = line[6:].strip()
    if not raw.isdigit():
        raise ToonDecodeError("@rows value must be non-negative integer")
    return int(raw)


def _parse_pipe_line(line: str) -> List[str]:
    text = line.strip()
    if len(text) < 2 or not text.startswith("|") or not text.endswith("|"):
        raise ToonDecodeError("table line must start and end with '|' ")

    cells: List[str] = []
    current: List[str] = []
    in_string = False
    escape = False
    depth = 0

    body = text[1:-1]
    for ch in body:
        if in_string:
            current.append(ch)
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            current.append(ch)
            continue

        if ch in "[{":
            depth += 1
            current.append(ch)
            continue
        if ch in "]}":
            depth = max(0, depth - 1)
            current.append(ch)
            continue

        if ch == "|" and depth == 0:
            cells.append("".join(current).strip())
            current = []
            continue

        current.append(ch)

    cells.append("".join(current).strip())
    return cells


def _normalize_lines(text: str) -> List[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return [line for line in normalized.split("\n") if line.strip() != ""]
