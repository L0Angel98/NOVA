from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Tuple

from .parser import parse_nova
from .toon import ToonDecodeError, decode_toon, encode_toon


AUTO_PREFIX = "sys."
DEFAULT_AGENT_PATH = "agent.toon"
DEFAULT_AGENT_DICTIONARY_PATH = "agent.dictionary.toon"
DEFAULT_AGENT_GUIDE_MD_PATH = "NOVA_LANGUAGE.md"
LEGACY_HEADER_PREFIX = "toon "


@dataclass(frozen=True)
class AgentRow:
    key: str
    value: str
    origin: str  # manual | auto


@dataclass(frozen=True)
class AgentSyncReport:
    path: Path
    manual_count: int
    auto_count: int
    total_count: int


@dataclass(frozen=True)
class AgentPackReport:
    text: str
    row_count: int


@dataclass(frozen=True)
class AgentCheckReport:
    ok: bool
    issues: List[str]


@dataclass(frozen=True)
class AgentInitReport:
    dictionary_path: Path
    guide_path: Path
    dictionary_written: bool
    guide_written: bool
    dictionary_rows: int


class AgentContextError(ValueError):
    pass


def default_agent_path(root: Path) -> Path:
    return root / DEFAULT_AGENT_PATH


def default_agent_dictionary_path(root: Path) -> Path:
    return root / DEFAULT_AGENT_DICTIONARY_PATH


def default_agent_guide_md_path(root: Path) -> Path:
    return root / DEFAULT_AGENT_GUIDE_MD_PATH


def init_agent_knowledge(
    root: Path,
    dictionary_path: Path,
    guide_path: Path,
    *,
    force: bool = False,
) -> AgentInitReport:
    rows = _default_dictionary_rows()
    dictionary_text = encode_toon(rows)
    guide_text = _default_language_guide_markdown(root.name or "project")

    dictionary_written = _write_if_allowed(dictionary_path, dictionary_text, force=force)
    guide_written = _write_if_allowed(guide_path, guide_text, force=force)

    return AgentInitReport(
        dictionary_path=dictionary_path,
        guide_path=guide_path,
        dictionary_written=dictionary_written,
        guide_written=guide_written,
        dictionary_rows=len(rows),
    )


def load_agent_rows(path: Path) -> List[AgentRow]:
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8")
    canonical_text = text.lstrip("\ufeff")
    stripped = canonical_text.strip()
    if stripped == "":
        return []

    if stripped.startswith("@toon v1"):
        return _load_v1_rows(canonical_text)

    if stripped.startswith(LEGACY_HEADER_PREFIX):
        return _load_legacy_rows(canonical_text)

    raise AgentContextError("agent.toon format not recognized")


def save_agent_rows(path: Path, rows: List[AgentRow]) -> None:
    canonical = _canonicalize_rows(rows)
    payload = [
        {"key": row.key, "value": row.value, "origin": row.origin}
        for row in canonical
    ]
    path.write_text(encode_toon(payload), encoding="utf-8")


def sync_agent(root: Path, agent_path: Path) -> AgentSyncReport:
    existing = load_agent_rows(agent_path)
    manual = [row for row in existing if not row.key.startswith(AUTO_PREFIX)]

    snapshot = build_snapshot(root)
    auto_rows = [
        AgentRow(key=key, value=_to_stable_value(value), origin="auto")
        for key, value in snapshot.items()
    ]

    merged = _canonicalize_rows(manual + auto_rows)
    save_agent_rows(agent_path, merged)

    return AgentSyncReport(
        path=agent_path,
        manual_count=len([row for row in merged if row.origin == "manual"]),
        auto_count=len([row for row in merged if row.origin == "auto"]),
        total_count=len(merged),
    )


def pack_agent(root: Path, agent_path: Path) -> AgentPackReport:
    rows = load_agent_rows(agent_path)
    if not rows:
        raise AgentContextError("agent.toon is empty or missing; run 'nova agt sync' first")

    kv = {row.key: row.value for row in rows}

    packed_pairs: List[Tuple[str, str]] = []
    for key in [
        "sys.agent.version",
        "sys.project.name",
        "sys.snapshot.digest",
        "sys.snapshot.file_count",
        "sys.snapshot.route_count",
        "sys.snapshot.test_count",
        "sys.cap.model",
    ]:
        if key in kv:
            packed_pairs.append((key, kv[key]))

    manual_rows = [row for row in rows if row.origin == "manual"]
    for row in sorted(manual_rows, key=lambda r: r.key):
        packed_pairs.append((row.key, row.value))

    compact = [{"k": k, "v": v} for k, v in packed_pairs]
    text = encode_toon(compact)
    return AgentPackReport(text=text, row_count=len(compact))


def check_agent(root: Path, agent_path: Path) -> AgentCheckReport:
    issues: List[str] = []
    rows = load_agent_rows(agent_path)
    if not rows:
        return AgentCheckReport(ok=False, issues=["agent.toon missing or empty"])

    seen: set[str] = set()
    for row in rows:
        if row.key in seen:
            issues.append(f"duplicate key: {row.key}")
        seen.add(row.key)
        if row.origin not in {"manual", "auto"}:
            issues.append(f"invalid origin for key '{row.key}': {row.origin}")

    kv = {row.key: row.value for row in rows}
    expected_snapshot = build_snapshot(root)

    for key, value in expected_snapshot.items():
        expected_value = _to_stable_value(value)
        actual = kv.get(key)
        if actual is None:
            issues.append(f"missing auto key: {key}")
            continue
        if key == "sys.snapshot.synced_at_utc":
            # Timestamp is advisory and intentionally excluded from drift check.
            continue
        if actual != expected_value:
            issues.append(f"drift on {key}: expected='{expected_value}' actual='{actual}'")

    if "sys.agent.version" not in kv:
        issues.append("missing auto key: sys.agent.version")

    return AgentCheckReport(ok=len(issues) == 0, issues=issues)


def build_snapshot(root: Path) -> Dict[str, Any]:
    files = list(_iter_project_files(root))

    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")

    nv_files = [path for path in files if path.suffix.lower() == ".nv"]
    route_count = 0
    parse_errors = 0
    for nv in nv_files:
        try:
            ast = parse_nova(nv.read_text(encoding="utf-8"))
            route_count += _count_nodes(ast, "RouteDecl")
        except Exception:
            parse_errors += 1

    test_count = 0
    for py in [path for path in files if path.suffix.lower() == ".py" and "/tests/" in f"/{path.relative_to(root).as_posix()}/"]:
        text = py.read_text(encoding="utf-8")
        test_count += len(re.findall(r"^\s*def\s+test_", text, flags=re.MULTILINE))

    root_name = root.name or root.as_posix()
    synced_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    return {
        "sys.agent.version": "agent.v0.1",
        "sys.project.name": root_name,
        "sys.snapshot.file_count": len(files),
        "sys.snapshot.nv_file_count": len(nv_files),
        "sys.snapshot.route_count": route_count,
        "sys.snapshot.test_count": test_count,
        "sys.snapshot.parse_error_count": parse_errors,
        "sys.snapshot.digest": digest.hexdigest()[:24],
        "sys.cap.model": "static-default-deny",
        "sys.commands": "parse,fmt,check,serve,agt init,agt pack,agt sync,agt chk",
        "sys.snapshot.synced_at_utc": synced_at,
    }


def _iter_project_files(root: Path) -> Iterable[Path]:
    allowed_suffixes = {".py", ".md", ".nv", ".toon"}
    ignored_parts = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".venv", "venv"}
    ignored_names = {"agent.toon", "agent.pack.toon"}

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        rel_parts = set(path.relative_to(root).parts)
        if rel_parts & ignored_parts:
            continue
        if path.name in ignored_names:
            continue

        if path.suffix.lower() in allowed_suffixes:
            yield path


def _count_nodes(node: Any, node_type: str) -> int:
    if isinstance(node, list):
        return sum(_count_nodes(item, node_type) for item in node)
    if not isinstance(node, dict):
        return 0

    count = 1 if node.get("type") == node_type else 0
    for value in node.values():
        count += _count_nodes(value, node_type)
    return count


def _load_v1_rows(text: str) -> List[AgentRow]:
    try:
        value = decode_toon(text)
    except ToonDecodeError as exc:
        raise AgentContextError(f"invalid v1 TOON in agent.toon: {exc}") from exc

    if not isinstance(value, list):
        raise AgentContextError("agent.toon v1 must decode to table rows")

    rows: List[AgentRow] = []
    for idx, row in enumerate(value):
        if not isinstance(row, dict):
            raise AgentContextError(f"agent.toon row {idx} is not object")
        key = str(row.get("key", "")).strip()
        val = row.get("value", "")
        origin = str(row.get("origin", "manual")).strip() or "manual"
        if key == "":
            raise AgentContextError(f"agent.toon row {idx} missing key")
        rows.append(AgentRow(key=key, value=_to_stable_value(val), origin=origin))
    return _canonicalize_rows(rows)


def _load_legacy_rows(text: str) -> List[AgentRow]:
    rows: List[AgentRow] = []
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    pipe_lines = [line.strip() for line in lines if line.strip().startswith("|") and line.strip().endswith("|")]
    if not pipe_lines:
        return []

    header_cells = [cell.strip() for cell in pipe_lines[0][1:-1].split("|")]
    if len(header_cells) < 2:
        raise AgentContextError("legacy agent.toon header must have at least 2 columns")

    key_col = 0
    value_col = 1
    lower_headers = [h.lower() for h in header_cells]
    if "key" in lower_headers:
        key_col = lower_headers.index("key")
    if "value" in lower_headers:
        value_col = lower_headers.index("value")

    for line in pipe_lines[1:]:
        cells = [cell.strip() for cell in line[1:-1].split("|")]
        if len(cells) <= max(key_col, value_col):
            continue
        key = cells[key_col]
        value = cells[value_col]
        if key == "":
            continue
        rows.append(AgentRow(key=key, value=_strip_wrapping_quotes(value), origin="manual"))

    return _canonicalize_rows(rows)


def _strip_wrapping_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and ((text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'")):
        return text[1:-1]
    return text


def _canonicalize_rows(rows: List[AgentRow]) -> List[AgentRow]:
    by_key: Dict[str, AgentRow] = {}
    for row in rows:
        key = row.key.strip()
        if key == "":
            continue
        origin = row.origin if row.origin in {"manual", "auto"} else "manual"
        by_key[key] = AgentRow(key=key, value=_to_stable_value(row.value), origin=origin)
    return sorted(by_key.values(), key=lambda row: row.key)


def _to_stable_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "nul"
    if isinstance(value, bool):
        return "tru" if value else "fal"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_if_allowed(path: Path, text: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _default_dictionary_rows() -> List[Dict[str, str]]:
    return [
        {
            "term": "mdl",
            "category": "keyword",
            "meaning": "Declaracion de modulo",
            "example": 'mdl demo v"0.1.0" rst<any, err> { ... }',
        },
        {
            "term": "rte",
            "category": "keyword",
            "meaning": "Declaracion de ruta HTTP",
            "example": 'rte "/items" GET json { ... }',
        },
        {
            "term": "GET|POST|PUT|PATCH|DELETE",
            "category": "keyword",
            "meaning": "Metodos HTTP canonicos",
            "example": "rte \"/items\" POST json { ... }",
        },
        {
            "term": "let",
            "category": "keyword",
            "meaning": "Binding inmutable",
            "example": 'let name = "nova"',
        },
        {
            "term": "if/els",
            "category": "keyword",
            "meaning": "Control de flujo condicional",
            "example": "if x == nul { ... } els { ... }",
        },
        {
            "term": "match",
            "category": "keyword",
            "meaning": "Pattern matching",
            "example": 'match state { "ok" => 1 _ => 0 }',
        },
        {
            "term": "grd",
            "category": "keyword",
            "meaning": "Validacion de presencia con error estandar",
            "example": 'grd body, body.name : "BAD_REQUEST"',
        },
        {
            "term": "tb/whe/lim/ord",
            "category": "keyword",
            "meaning": "DB IR declarativo",
            "example": "tb users.q { whe active == tru ord id desc lim num10 }",
        },
        {
            "term": "cap",
            "category": "keyword",
            "meaning": "Declaracion de capabilities estaticas",
            "example": "cap [db, env]",
        },
        {
            "term": "rst.ok / err",
            "category": "result",
            "meaning": "Contrato de salida para rutas",
            "example": 'rst.ok({ok: tru}) / err {code: "BAD_REQUEST", msg: "..."}',
        },
        {
            "term": "json / toon",
            "category": "format",
            "meaning": "Formatos de respuesta",
            "example": "rte \"/items\" GET toon { ... }",
        },
        {
            "term": "str literal",
            "category": "literal",
            "meaning": 'String se expresa como "..." (sin prefijo str)',
            "example": 'let title = "hello"',
        },
        {
            "term": "num literal",
            "category": "literal",
            "meaning": "Numero con prefijo num",
            "example": "lim num50",
        },
        {
            "term": "tru/fal/nul",
            "category": "literal",
            "meaning": "Booleanos y nulo canonicos",
            "example": "if body == nul { ... }",
        },
        {
            "term": "module_default_result",
            "category": "nomenclature",
            "meaning": "Tipo rst por defecto en firma de modulo",
            "example": 'mdl demo v"0.1.0" rst<any, err> { ... }',
        },
        {
            "term": "runtime_error_toon",
            "category": "nomenclature",
            "meaning": "Errores de parse/runtime en formato TOON estructurado",
            "example": '@toon v1 + @type error + |k|v|',
        },
    ]


def _default_language_guide_markdown(project_name: str) -> str:
    return f"""# NOVA Language Notes

Proyecto: {project_name}

Este documento define sintaxis y nomenclatura minima para que un agente IA trabaje el codigo NOVA sin ambiguedad.

## Firma de modulo

```nova
mdl <name> v"x.y.z" rst<any, err> {{
  ...
}}
```

Reglas:
- La version del modulo usa `v"..."`.
- El tipo `rst<any, err>` puede declararse una sola vez en la firma del modulo.

## Rutas HTTP

```nova
rte "/path" GET json {{
  ...
}}
```

Reglas:
- Metodos HTTP son keywords: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`.
- No usar metodos como string (`"GET"`).
- El formato de salida es `json` o `toon`.

## Literales

- Strings: `"..."` (sin prefijo `str`).
- Numeros: `num10`, `num3.14`.
- Booleanos: `tru` / `fal`.
- Nulo: `nul`.

## Flujo y validacion

- `let` para bindings inmutables.
- `if / els` para ramas condicionales.
- `match` para pattern matching.
- `grd` para validar presencia de campos requeridos:

```nova
grd body, body.name : "BAD_REQUEST"
```

## DB IR declarativo

```nova
tb users.q {{
  whe active == tru
  ord id desc
  lim num10
}}
```

Reglas:
- `tb` define tabla objetivo.
- `whe`, `ord`, `lim` son clausulas declarativas.
- `cap [db]` puede inferirse cuando la ruta usa `tb`.

## Capabilities

- Modelo default-deny: `net`, `db`, `env`, `fs`.
- Declarar caps explicitamente cuando aplique:

```nova
cap [env, fs]
```

## Resultado y errores

- Exito: `rst.ok(value)`.
- Error: `err {{code: "...", msg: "..."}}`.
- Error de runtime/parse esperado por agentes en TOON estructurado:

```toon
@toon v1
@type error
|k|v|
|"line"|"12"|
|"token"|"whe"|
|"expected"|"tb antes de whe"|
|"file"|"app.nv"|
|"severity"|"error"|
```
"""
