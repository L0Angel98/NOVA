from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List

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
    agent_written = _init_index(root, agent_path, force=force)
    sync = sync_agent(root, agent_path)

    # Legacy files are kept as optional placeholders for backwards compatibility.
    dictionary_written = _write_if_allowed(dictionary_path, encode_toon([]), force=force)
    guide_written = _write_if_allowed(guide_path, "# NOVA Language Notes\n", force=force)

    return AgentInitReport(
        agent_path=sync.path,
        dictionary_path=dictionary_path,
        guide_path=guide_path,
        agent_written=agent_written,
        dictionary_written=dictionary_written,
        guide_written=guide_written,
        agent_rows=sync.file_count,
        dictionary_rows=0,
    )


def sync_agent(root: Path, agent_path: Path | None = None) -> AgentSyncReport:
    path = agent_path if agent_path is not None else default_agent_path(root)
    if not path.exists():
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
        "v": "0.1.3",
        "rt": ".",
        "sum": summary,
        "api": routes,
        "cap": caps,
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
        "v": "0.1.3",
        "rt": ".",
        "sum": [],
        "api": [],
        "cap": [],
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
