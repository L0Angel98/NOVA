from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
import subprocess
import sys

from .agent_context import (
    AgentContextError,
    check_agent,
    default_agent_path,
    init_agent_knowledge,
    pack_agent,
    sync_agent,
)
from .ast_utils import ast_to_json
from .backends import BackendError, get_backend
from .checker import check_ast, format_diagnostics
from .formatter import format_nova
from .ir import IrEmitError, emit_ir, ir_to_json
from .parser import parse_nova
from .runtime import RuntimeBuildError, run_server
from .version import VERSION


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_ir(src_path: Path, out_dir: Path) -> tuple[Path, object]:
    source = _read_text(src_path)
    ast = parse_nova(source)
    ir = emit_ir(ast, source_path=src_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    ir_path = out_dir / f"{src_path.stem}.ir.json"
    ir_path.write_text(ir_to_json(ir) + "\n", encoding="utf-8")
    return ir_path, ir


def _caps(args: argparse.Namespace) -> set[str]:
    return {str(item).strip() for item in getattr(args, "capabilities", []) if str(item).strip() != ""}


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


def cmd_build(args: argparse.Namespace) -> int:
    src_path = Path(args.input).resolve()
    out_dir = Path(args.out_dir).resolve()
    caps = _caps(args)

    try:
        ir_path, ir = _write_ir(src_path, out_dir)
        backend = get_backend(args.backend)
        result = backend.build(ir=ir, ir_path=ir_path, src_path=src_path, out_dir=out_dir, caps=caps)
    except (IrEmitError, BackendError, RuntimeError, ValueError) as exc:
        sys.stdout.write(f"[NVB100] build: {exc}\n")
        return 2

    sys.stdout.write(f"build ok backend={result.backend} ir={result.ir_path} out={result.artifact}\n")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    src_path = Path(args.input).resolve()
    out_dir = Path(args.out_dir).resolve()
    caps = _caps(args)

    try:
        ir_path, ir = _write_ir(src_path, out_dir)
        backend = get_backend(args.backend)
        code = backend.run(ir=ir, ir_path=ir_path, src_path=src_path, out_dir=out_dir, caps=caps)
    except (IrEmitError, BackendError, RuntimeError, ValueError) as exc:
        sys.stdout.write(f"[NVB101] run: {exc}\n")
        return 2

    return int(code)


def cmd_serve(args: argparse.Namespace) -> int:
    if args.backend == "llvm":
        src_path = Path(args.entry).resolve()
        out_dir = Path(args.out_dir).resolve()
        caps = _caps(args)
        out_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="nova-llvm-serve-", dir=str(out_dir)) as tmp:
            tmp_out = Path(tmp)
            try:
                ir_path, ir = _write_ir(src_path, tmp_out)
                backend = get_backend("llvm")
                result = backend.build(
                    ir=ir,
                    ir_path=ir_path,
                    src_path=src_path,
                    out_dir=tmp_out,
                    caps=caps,
                )
            except (IrEmitError, BackendError, RuntimeError, ValueError) as exc:
                sys.stdout.write(f"[NVR100] build llvm: {exc}\n")
                return 2

            cmd = [str(result.artifact), "--port", str(args.port), "--root", str(Path(args.root).resolve())]
            for cap in sorted(caps):
                cmd.extend(["--cap", cap])
            try:
                proc = subprocess.Popen(cmd)
                return int(proc.wait())
            except KeyboardInterrupt:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
                return 130
            except Exception as exc:
                if "proc" in locals() and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        proc.kill()
                sys.stdout.write(f"[NVR101] serve llvm: {exc}\n")
                return 2

    if args.backend != "interp":
        sys.stdout.write("[NVR099] serve: unsupported backend for serve\n")
        return 2

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

    try:
        result = pack_agent(root, agent_path)
    except AgentContextError as exc:
        sys.stdout.write(f"[NVA100] agt pack: {exc}\n")
        return 2

    if args.output:
        output_path = Path(args.output).resolve()
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
        f"sync ok file={result.path} files={result.file_count} routes={result.route_count} caps={result.cap_count}\n"
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


import importlib.resources
import shutil

def cmd_agt_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()

    try:
        report = init_agent_knowledge(
            root,
            root / "agent.dictionary.toon",
            root / "NOVA_LANGUAGE.md",
            force=bool(args.force),
        )
    except AgentContextError as exc:
        sys.stdout.write(f"[NVA103] agt init: {exc}\n")
        return 2
    except Exception as exc:
        sys.stdout.write(f"[NVA103] agt init: {exc}\n")
        return 2

    # Copiar nova_skill.md al proyecto
    skill_dst = root / "nova_skill.md"
    if not skill_dst.exists() or bool(args.force):
        try:
            skill_src = Path(__file__).parent / "data" / "nova_skill.md"
            shutil.copy2(skill_src, skill_dst)
            skill_status = "written"
        except Exception as exc:
            skill_status = f"skipped ({exc})"
    else:
        skill_status = "kept"

    dict_status = "written" if report.dictionary_written else "kept"
    md_status = "written" if report.guide_written else "kept"
    agent_status = "written" if report.agent_written else "kept"
    sys.stdout.write(
        "init ok "
        f"agent={report.agent_path} ({agent_status}) "
        f"dict={report.dictionary_path} ({dict_status}) "
        f"md={report.guide_path} ({md_status}) "
        f"skill=nova_skill.md ({skill_status}) "
        f"agent_rows={report.agent_rows} dict_rows={report.dictionary_rows}\n"
    )
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nova", description=f"NOVA v{VERSION} parser + runtime + backends")
    parser.add_argument("--version", action="version", version=f"nova {VERSION}")

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

    p_build = sub.add_parser("build", help="Compile .nv to backend artifact")
    p_build.add_argument("input", help="Input .nv file")
    p_build.add_argument("--b", dest="backend", default="interp", choices=["llvm", "go", "interp"], help="Backend")
    p_build.add_argument("--out-dir", default="out", help="Output directory (default: out)")
    p_build.add_argument(
        "--cap",
        dest="capabilities",
        action="append",
        default=[],
        help="Grant static capability (repeatable): net|html|db|env|fs",
    )
    p_build.set_defaults(func=cmd_build)

    p_run = sub.add_parser("run", help="Run .nv using selected backend")
    p_run.add_argument("input", help="Input .nv file")
    p_run.add_argument("--b", dest="backend", default="interp", choices=["llvm", "go", "interp"], help="Backend")
    p_run.add_argument("--out-dir", default="out", help="Output directory (default: out)")
    p_run.add_argument(
        "--cap",
        dest="capabilities",
        action="append",
        default=[],
        help="Grant static capability (repeatable): net|html|db|env|fs",
    )
    p_run.set_defaults(func=cmd_run)

    p_serve = sub.add_parser("serve", help="Run NOVA HTTP runtime")
    p_serve.add_argument("entry", help="Entry .nv app file")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=3000, help="Bind port (default: 3000)")
    p_serve.add_argument("--b", dest="backend", default="interp", choices=["interp", "llvm", "go"], help="Backend")
    p_serve.add_argument("--out-dir", default="out", help="Build output dir for llvm mode")
    p_serve.add_argument("--root", default=".", help="Project root for llvm relative paths")
    p_serve.add_argument(
        "--cap",
        dest="capabilities",
        action="append",
        default=[],
        help="Grant static capability (repeatable): net|html|db|env|fs",
    )
    p_serve.set_defaults(func=cmd_serve)

    p_agt = sub.add_parser("agt", help="Agent context index (.nova/idx.toon)")
    agt_sub = p_agt.add_subparsers(dest="agt_command", required=True)

    p_agt_init = agt_sub.add_parser("init", help="Create .nova/idx.toon")
    p_agt_init.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_init.add_argument("--force", action="store_true", help="Overwrite idx.toon if it already exists")
    p_agt_init.set_defaults(func=cmd_agt_init)

    p_agt_sync = agt_sub.add_parser("sync", help="Sync .nova/idx.toon from project snapshot")
    p_agt_sync.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_sync.add_argument("--file", help="Path to idx.toon (default: <root>/.nova/idx.toon)")
    p_agt_sync.set_defaults(func=cmd_agt_sync)

    p_agt_chk = agt_sub.add_parser("chk", help="Validate .nova/idx.toon")
    p_agt_chk.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_chk.add_argument("--file", help="Path to idx.toon (default: <root>/.nova/idx.toon)")
    p_agt_chk.set_defaults(func=cmd_agt_chk)

    p_agt_check = agt_sub.add_parser("check", help="Alias of agt chk")
    p_agt_check.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_check.add_argument("--file", help="Path to idx.toon (default: <root>/.nova/idx.toon)")
    p_agt_check.set_defaults(func=cmd_agt_chk)

    p_agt_pack = agt_sub.add_parser("pack", help="Emit compact context payload")
    p_agt_pack.add_argument("--root", default=".", help="Project root (default: current dir)")
    p_agt_pack.add_argument("--file", help="Path to idx.toon (default: <root>/.nova/idx.toon)")
    p_agt_pack.add_argument("--output", help="Write packed payload to file (default: stdout)")
    p_agt_pack.set_defaults(func=cmd_agt_pack)

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
