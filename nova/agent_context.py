from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Tuple

from .parser import parse_nova
from .toon import ToonDecodeError, decode_toon, encode_toon


DEFAULT_AGENT_PATH = ".nova/idx.toon"
DEFAULT_AGENT_DICTIONARY_PATH = "agent.dictionary.toon"
DEFAULT_AGENT_GUIDE_MD_PATH = "NOVA_LANGUAGE.md"

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    ".next",
    ".idea",
    ".vscode",
}

REQUIRED_KEYS = ["v", "rt", "sum", "api", "cap", "m", "dep", "chg", "ts"]
NET_DRV_META = {
    "net": ["py", "node", "browser"],
    "sel": "env:NOVA_NET_DRIVER",
    "nt": "browser=headless,install_chromium,js",
}
AGT_CTX_FILES = [".nova/idx.toon", "agent.dictionary.toon", "NOVA_LANGUAGE.md"]
AGT_PROMPT = "read ctxf first; on project change run agt sync; before answer run agt pack"


@dataclass(frozen=True)
class AgentSyncReport:
    path: Path
    file_count: int
    route_count: int
    cap_count: int


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
    agent_path: Path
    dictionary_path: Path
    guide_path: Path
    agent_written: bool
    dictionary_written: bool
    guide_written: bool
    agent_rows: int
    dictionary_rows: int


@dataclass(frozen=True)
class AgentRow:
    key: str
    value: str
    origin: str  # manual | auto


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
    agent_path = default_agent_path(root)
    agent_rows = _default_agent_rows(root)
    agent_text = encode_toon(
        [{"key": row.key, "value": row.value, "origin": row.origin} for row in agent_rows]
    )

    rows = _default_dictionary_rows()
    dictionary_text = encode_toon(rows)
    guide_text = _default_language_guide_markdown(root.name or "project")

    agent_written = _write_if_allowed(agent_path, agent_text, force=force)
    dictionary_written = _write_if_allowed(dictionary_path, dictionary_text, force=force)
    guide_written = _write_if_allowed(guide_path, guide_text, force=force)

    return AgentInitReport(
        agent_path=agent_path,
        dictionary_path=dictionary_path,
        guide_path=guide_path,
        agent_written=agent_written,
        dictionary_written=dictionary_written,
        guide_written=guide_written,
        agent_rows=len(agent_rows),
        dictionary_rows=len(rows),
    )


def sync_agent(root: Path, agent_path: Path | None = None) -> AgentSyncReport:
    path = agent_path if agent_path is not None else default_agent_path(root)
    if not path.exists():
        _init_index(root, path, force=True)

    try:
        previous = _read_index(path)
    except AgentContextError:
        # agt init may leave a doc table; reset to idx object before sync.
        _init_index(root, path, force=True)
        previous = _read_index(path)
    files = list(_iter_project_files(root))
    routes = _scan_routes(root, files)
    caps = _scan_caps(root, files)
    deps = _scan_deps(root)

    summary = _build_summary(root, files, routes, caps)
    fmap = _important_map(root)
    ts = _build_ts(root, files)

    chg = []
    if isinstance(previous.get("chg"), list):
        chg = [item for item in previous["chg"] if isinstance(item, dict)]
    chg.append({"at": _utc_now_iso(), "op": "sync"})
    if len(chg) > 20:
        chg = chg[-20:]

    idx = {
        "v": "0.1.6",
        "rt": ".",
        "sum": summary,
        "api": routes,
        "cap": caps,
        "nd": NET_DRV_META,
        "ctxf": AGT_CTX_FILES,
        "prm": AGT_PROMPT,
        "m": fmap,
        "dep": deps,
        "chg": chg,
        "ts": ts,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode_toon(idx), encoding="utf-8")
    return AgentSyncReport(path=path, file_count=len(files), route_count=len(routes), cap_count=len(caps))


def check_agent(root: Path, agent_path: Path | None = None) -> AgentCheckReport:
    path = agent_path if agent_path is not None else default_agent_path(root)
    if not path.exists():
        return AgentCheckReport(ok=False, issues=["idx.toon missing"])

    try:
        idx = _read_index(path)
    except AgentContextError as exc:
        return AgentCheckReport(ok=False, issues=[str(exc)])

    issues: List[str] = []
    for key in REQUIRED_KEYS:
        if key not in idx:
            issues.append(f"missing key: {key}")

    if not isinstance(idx.get("sum"), list):
        issues.append("sum must be list")
    if not isinstance(idx.get("api"), list):
        issues.append("api must be list")
    if not isinstance(idx.get("cap"), list):
        issues.append("cap must be list")
    if not isinstance(idx.get("m"), dict):
        issues.append("m must be object")
    if not isinstance(idx.get("dep"), list):
        issues.append("dep must be list")
    if not isinstance(idx.get("chg"), list):
        issues.append("chg must be list")
    if not isinstance(idx.get("ts"), dict):
        issues.append("ts must be object")

    return AgentCheckReport(ok=len(issues) == 0, issues=issues)


def pack_agent(root: Path, agent_path: Path | None = None) -> AgentPackReport:
    path = agent_path if agent_path is not None else default_agent_path(root)
    idx = _read_index(path)
    compact = {
        "v": idx.get("v"),
        "rt": idx.get("rt"),
        "sum": idx.get("sum", [])[:12],
        "api": idx.get("api", [])[:32],
        "cap": idx.get("cap", []),
        "dep": idx.get("dep", []),
    }
    text = encode_toon(compact)
    row_count = len(compact.get("sum", [])) + len(compact.get("api", []))
    return AgentPackReport(text=text, row_count=row_count)


def _init_index(root: Path, path: Path, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    template = {
        "v": "0.1.6",
        "rt": ".",
        "sum": [],
        "api": [],
        "cap": [],
        "nd": NET_DRV_META,
        "ctxf": AGT_CTX_FILES,
        "prm": AGT_PROMPT,
        "m": {},
        "dep": [],
        "chg": [{"at": _utc_now_iso(), "op": "init"}],
        "ts": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encode_toon(template), encoding="utf-8")
    return True


def _read_index(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise AgentContextError("idx.toon missing")
    text = path.read_text(encoding="utf-8")
    try:
        value = decode_toon(text)
    except ToonDecodeError as exc:
        raise AgentContextError(f"invalid idx.toon: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentContextError("idx.toon must decode to object")
    return value


def _iter_project_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if rel.as_posix().startswith(".nova/"):
            continue
        yield path


def _scan_routes(root: Path, files: List[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for file in files:
        if file.suffix.lower() != ".nv":
            continue
        try:
            ast = parse_nova(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for route in _collect_nodes(ast, "RouteDecl"):
            out.append(
                {
                    "m": _method_name(route.get("method")),
                    "p": _str_expr(route.get("path")),
                    "f": _str_expr(route.get("format"), default="json"),
                    "s": file.relative_to(root).as_posix(),
                }
            )
    out.sort(key=lambda item: (item.get("p", ""), item.get("m", ""), item.get("s", "")))
    return out


def _scan_caps(root: Path, files: List[Path]) -> List[str]:
    caps: set[str] = set()
    for file in files:
        if file.suffix.lower() != ".nv":
            continue
        try:
            ast = parse_nova(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in _collect_nodes(ast, "CapStmt"):
            caps.update(_caps_from_expr(node.get("value")))
        for call in _collect_nodes(ast, "CallExpr"):
            fn = _callee_name(call.get("callee"))
            if fn.startswith("http.") or fn.startswith("net."):
                caps.add("net")
            if fn.startswith("html."):
                caps.add("html")
            if fn.startswith("db."):
                caps.add("db")
    return sorted(caps)


def _scan_deps(root: Path) -> List[str]:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return []
    text = pyproject.read_text(encoding="utf-8")

    deps: List[str] = []
    in_deps = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies") and "[" in stripped:
            in_deps = True
            continue
        if in_deps and stripped.startswith("]"):
            break
        if in_deps:
            item = stripped.strip(",").strip().strip('"').strip("'")
            if item:
                deps.append(item)
    return deps


def _build_summary(root: Path, files: List[Path], routes: List[Dict[str, Any]], caps: List[str]) -> List[str]:
    nv_count = len([f for f in files if f.suffix.lower() == ".nv"])
    py_count = len([f for f in files if f.suffix.lower() == ".py"])
    md_count = len([f for f in files if f.suffix.lower() == ".md"])
    demo_count = len([f for f in files if f.relative_to(root).as_posix().startswith("demo/")])

    lines = [
        f"project={root.name or root.as_posix()}",
        f"files={len(files)}",
        f"nv={nv_count}",
        f"py={py_count}",
        f"md={md_count}",
        f"demo={demo_count}",
        f"routes={len(routes)}",
        f"caps={','.join(caps) if caps else '-'}",
        f"ts={_utc_now_iso()}",
    ]

    top = [p.relative_to(root).as_posix() for p in sorted(files)[:8]]
    for rel in top:
        lines.append(f"f:{rel}")

    if len(lines) < 10:
        lines.append("sync=ok")
    return lines[:20]


def _default_language_guide_markdown(project_name: str) -> str:
    return (
        "# NOVA Language Notes\n\n"
        f"Proyecto: {project_name}\n\n"
        "Guia minima para agentes IA sobre sintaxis y capacidades del runtime.\n"
    )


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


def _canonicalize_rows(rows: List[AgentRow]) -> List[AgentRow]:
    by_key: Dict[str, AgentRow] = {}
    for row in rows:
        key = row.key.strip()
        if key == "":
            continue
        origin = row.origin if row.origin in {"manual", "auto"} else "manual"
        by_key[key] = AgentRow(key=key, value=_to_stable_value(row.value), origin=origin)
    return sorted(by_key.values(), key=lambda row: row.key)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_agent_rows(root: Path) -> List[AgentRow]:
    gen = {
        "by": "nova",
        "at": _utc_now_iso(),
        "os": platform.system().lower(),
        "py": ".".join(str(part) for part in sys.version_info[:3]),
    }
    ignores = [
        ".git",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        ".next",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
    ]
    ns = {"ctx": "reserved", "db": "reserved"}
    cxa = {"q": "query", "p": "params", "h": "headers", "b": "body"}
    cap = {"net": "http.get", "html": ["tte", "sct"]}
    nd = NET_DRV_META
    ctxf = AGT_CTX_FILES
    prm = AGT_PROMPT
    fs = {"ent": len(list(_iter_project_files(root))), "upd": _utc_now_iso()}
    fls = _important_files(root, max_items=30)
    tsk = ["sync", "chk", "pack"]
    legacy = {"routes": [], "tests": [], "synced_at_utc": ""}

    manual_rows = [
        AgentRow(key="v", value="0.1.6", origin="manual"),
        AgentRow(key="k", value="agt", origin="manual"),
        AgentRow(key="gen", value=_to_stable_value(gen), origin="manual"),
        AgentRow(key="rt", value=".", origin="manual"),
        AgentRow(key="pn", value=root.name or root.as_posix(), origin="manual"),
        AgentRow(key="ig", value=_to_stable_value(ignores), origin="manual"),
        AgentRow(key="ns", value=_to_stable_value(ns), origin="manual"),
        AgentRow(key="cxa", value=_to_stable_value(cxa), origin="manual"),
        AgentRow(key="cap", value=_to_stable_value(cap), origin="manual"),
        AgentRow(key="nd", value=_to_stable_value(nd), origin="manual"),
        AgentRow(key="ctxf", value=_to_stable_value(ctxf), origin="manual"),
        AgentRow(key="prm", value=prm, origin="manual"),
        AgentRow(key="fs", value=_to_stable_value(fs), origin="manual"),
        AgentRow(key="fls", value=_to_stable_value(fls), origin="manual"),
        AgentRow(key="tsk", value=_to_stable_value(tsk), origin="manual"),
        AgentRow(key="leg", value=_to_stable_value(legacy), origin="manual"),
    ]
    return _canonicalize_rows(manual_rows)


def _important_files(root: Path, *, max_items: int) -> List[str]:
    selected: List[str] = []
    seen: set[str] = set()

    def add_path(path: Path) -> None:
        rel = path.relative_to(root).as_posix()
        if rel in seen:
            return
        seen.add(rel)
        selected.append(rel)

    for relative in [Path("README.md"), Path("SPEC.md"), Path("pyproject.toml")]:
        path = root / relative
        if path.exists() and path.is_file():
            add_path(path)

    demo_dir = root / "demo"
    if demo_dir.exists():
        for path in sorted(demo_dir.glob("*.nv")):
            if path.is_file():
                add_path(path)

    nova_dir = root / "nova"
    if nova_dir.exists():
        for path in sorted(nova_dir.rglob("*")):
            if path.is_file():
                add_path(path)

    return selected[:max_items]


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

    top = [p.relative_to(root).as_posix() for p in sorted(files)[:8]]
    for rel in top:
        lines.append(f"f:{rel}")

    if len(lines) < 10:
        lines.append("sync=ok")
    return lines[:20]


def _important_map(root: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in ["README.md", "SPEC.md", "pyproject.toml", "nova/cli.py", "nova/runtime.py"]:
        path = root / name
        if path.exists() and path.is_file():
            out[name] = "core"

    demos: List[str] = []
    demo_dir = root / "demo"
    if demo_dir.exists() and demo_dir.is_dir():
        for path in sorted(demo_dir.glob("*.nv")):
            demos.append(path.relative_to(root).as_posix())
    if demos:
        out["demo"] = demos

    return out


def _build_ts(root: Path, files: List[Path]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for file in files:
        rel = file.relative_to(root).as_posix()
        stat = file.stat()
        digest = hashlib.sha1(file.read_bytes()).hexdigest()[:12]
        out[rel] = {"m": int(stat.st_mtime), "h": digest, "s": int(stat.st_size)}
    return out


def _collect_nodes(node: Any, kind: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if isinstance(node, list):
        for item in node:
            out.extend(_collect_nodes(item, kind))
        return out
    if not isinstance(node, dict):
        return out
    if node.get("type") == kind:
        out.append(node)
    for value in node.values():
        out.extend(_collect_nodes(value, kind))
    return out


def _method_name(expr: Any) -> str:
    raw = _str_expr(expr, default="GET").upper()
    aliases = {"DEL": "DELETE", "PAT": "PATCH", "OPT": "OPTIONS", "HED": "HEAD"}
    return aliases.get(raw, raw)


def _str_expr(expr: Any, default: str = "") -> str:
    if not isinstance(expr, dict):
        return default
    typ = expr.get("type")
    if typ == "StringLiteral":
        return str(expr.get("value", default))
    if typ == "Identifier":
        return str(expr.get("name", default))
    return default


def _caps_from_expr(expr: Any) -> List[str]:
    if not isinstance(expr, dict):
        return []
    typ = expr.get("type")
    if typ == "ArrayLiteral":
        out: List[str] = []
        for item in expr.get("items", []):
            out.extend(_caps_from_expr(item))
        return out
    if typ == "Identifier":
        return [str(expr.get("name", "")).strip()]
    if typ == "StringLiteral":
        return [str(expr.get("value", "")).strip()]
    return []


def _callee_name(expr: Any) -> str:
    if not isinstance(expr, dict):
        return ""
    typ = expr.get("type")
    if typ == "Identifier":
        return str(expr.get("name", ""))
    if typ == "MemberExpr":
        left = _callee_name(expr.get("object"))
        right = str(expr.get("property", ""))
        if left == "":
            return right
        return f"{left}.{right}"
    return ""


def _write_if_allowed(path: Path, text: str, *, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
