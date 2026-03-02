from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .ast_utils import ast_to_json
from .agent_context import (
    AgentContextError,
    check_agent,
    default_agent_dictionary_path,
    default_agent_guide_md_path,
    default_agent_path,
    init_agent_knowledge,
    pack_agent,
    sync_agent,
)
from .checker import format_diagnostics, check_ast
from .formatter import format_nova
from .parser import parse_nova
from .runtime import RuntimeBuildError, run_server


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def cmd_parse(args: argparse.Namespace) -> int:
    source = _read_text(Path(args.input))
    ast = parse_nova(source)
    output = ast_to_json(ast)

    if args.output:
        Path(args.output).write_text(output + "\n", encoding="utf-8")
    else:
        sys.stdout.write(output + "\n")
    return 0


def cmd_fmt(args: argparse.Namespace) -> int:
    path = Path(args.input)
    source = _read_text(path)
    ast = parse_nova(source)
    formatted = format_nova(ast)

    if args.write:
        path.write_text(formatted, encoding="utf-8")
    else:
        sys.stdout.write(formatted)
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    source = _read_text(Path(args.input))
    try:
        ast = parse_nova(source)
    except Exception as exc:  # Parse/lex errors are reported deterministically for check
        sys.stdout.write(f"[NVC900] parse: {exc}\n")
        return 2

    try:
        result = check_ast(ast)
    except Exception as exc:
        sys.stdout.write(f"[NVC901] checker: {exc}\n")
        return 2
    if result.ok:
        sys.stdout.write("OK\n")
        return 0

    sys.stdout.write(format_diagnostics(result.diagnostics) + "\n")
    return 1


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        server = run_server(args.entry, host=args.host, port=args.port, capabilities=args.capabilities)
    except RuntimeBuildError as exc:
        sys.stdout.write(f"[NVR100] build: {exc}\n")
        return 2
    except Exception as exc:
        sys.stdout.write(f"[NVR101] serve: {exc}\n")
        return 2

    host, port = server.server_address
    sys.stdout.write(f"NOVA HTTP server listening on http://{host}:{port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_agt_pack(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    agent_path = Path(args.file).resolve() if args.file else default_agent_path(root)
    output_path = Path(args.output).resolve() if args.output else None

    try:
        result = pack_agent(root, agent_path)
    except AgentContextError as exc:
        sys.stdout.write(f"[NVA100] agt pack: {exc}\n")
        return 2

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.text, encoding="utf-8")
        sys.stdout.write(f"packed rows={result.row_count} -> {output_path}\n")
    else:
        sys.stdout.write(result.text)
    return 0


def cmd_agt_sync(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    agent_path = Path(args.file).resolve() if args.file else default_agent_path(root)

    try:
        result = sync_agent(root, agent_path)
    except AgentContextError as exc:
        sys.stdout.write(f"[NVA101] agt sync: {exc}\n")
        return 2

    sys.stdout.write(
        f"sync ok file={result.path} manual={result.manual_count} auto={result.auto_count} total={result.total_count}\n"
    )
    return 0


def cmd_agt_chk(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    agent_path = Path(args.file).resolve() if args.file else default_agent_path(root)

    try:
        result = check_agent(root, agent_path)
    except AgentContextError as exc:
        sys.stdout.write(f"[NVA102] agt chk: {exc}\n")
        return 2

    if result.ok:
        sys.stdout.write("OK\n")
        return 0

    for issue in result.issues:
        sys.stdout.write(f"- {issue}\n")
    return 1


def cmd_agt_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    dictionary_path = Path(args.dict_file).resolve() if args.dict_file else default_agent_dictionary_path(root)
    guide_path = Path(args.md_file).resolve() if args.md_file else default_agent_guide_md_path(root)

    try:
        result = init_agent_knowledge(
            root,
            dictionary_path,
            guide_path,
            force=bool(args.force),
        )
    except AgentContextError as exc:
        sys.stdout.write(f"[NVA103] agt init: {exc}\n")
        return 2
    except Exception as exc:
        sys.stdout.write(f"[NVA103] agt init: {exc}\n")
        return 2

    dict_status = "written" if result.dictionary_written else "kept"
    md_status = "written" if result.guide_written else "kept"
    sys.stdout.write(
        f"init ok dict={result.dictionary_path} ({dict_status}) md={result.guide_path} ({md_status}) rows={result.dictionary_rows}\n"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova", description="NOVA v0.1 parser + formatter + checker + runtime")
    sub = parser.add_subparsers(dest="command", required=True)

    p_parse = sub.add_parser("parse", help="Parse .nv source and output typed AST JSON")
    p_parse.add_argument("input", help="Input .nv file")
    p_parse.add_argument("-o", "--output", help="Output JSON file")
    p_parse.set_defaults(func=cmd_parse)

    p_fmt = sub.add_parser("fmt", help="Canonical NOVA formatter")
    p_fmt.add_argument("input", help="Input .nv file")
    p_fmt.add_argument("-w", "--write", action="store_true", help="Write result in place")
    p_fmt.set_defaults(func=cmd_fmt)

    p_check = sub.add_parser("check", help="Static type checker (no runtime)")
    p_check.add_argument("input", help="Input .nv file")
    p_check.set_defaults(func=cmd_check)

    p_serve = sub.add_parser("serve", help="Run NOVA HTTP runtime")
    p_serve.add_argument("entry", help="Entry .nv app file")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8080, help="Bind port (default: 8080)")
    p_serve.add_argument(
        "--cap",
        dest="capabilities",
        action="append",
        default=[],
        help="Grant static capability (repeatable): net|db|env|fs",
    )
    p_serve.set_defaults(func=cmd_serve)

    p_agt = sub.add_parser("agt", help="Agent Context system")
    agt_sub = p_agt.add_subparsers(dest="agt_command", required=True)

    p_agt_pack = agt_sub.add_parser("pack", help="Build compact AI context payload from agent.toon")
    p_agt_pack.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_pack.add_argument("--file", help="Path to agent.toon (default: <root>/agent.toon)")
    p_agt_pack.add_argument("--output", help="Write packed payload to file (default: stdout)")
    p_agt_pack.set_defaults(func=cmd_agt_pack)

    p_agt_sync = agt_sub.add_parser("sync", help="Sync agent.toon auto fields from project snapshot")
    p_agt_sync.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_sync.add_argument("--file", help="Path to agent.toon (default: <root>/agent.toon)")
    p_agt_sync.set_defaults(func=cmd_agt_sync)

    p_agt_chk = agt_sub.add_parser("chk", help="Validate agent.toon and detect drift")
    p_agt_chk.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_chk.add_argument("--file", help="Path to agent.toon (default: <root>/agent.toon)")
    p_agt_chk.set_defaults(func=cmd_agt_chk)

    p_agt_init = agt_sub.add_parser("init", help="Generate NOVA agent dictionary (.toon) and language guide (.md)")
    p_agt_init.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_init.add_argument("--dict-file", help="Output TOON dictionary file (default: <root>/agent.dictionary.toon)")
    p_agt_init.add_argument("--md-file", help="Output language guide markdown file (default: <root>/NOVA_LANGUAGE.md)")
    p_agt_init.add_argument("--force", action="store_true", help="Overwrite files if they already exist")
    p_agt_init.set_defaults(func=cmd_agt_init)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
