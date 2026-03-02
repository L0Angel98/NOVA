from __future__ import annotations

from pathlib import Path
import platform
import shutil
import subprocess
from typing import Set

from nova.ir.nodes import IrMdl

from .base import BackendBuildResult, BackendError


class LlvmBackend:
    name = "llvm"

    def build(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> BackendBuildResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".exe" if platform.system().lower().startswith("win") else ""
        artifact = out_dir / f"{src_path.stem}{suffix}"
        self._prepare_artifact_paths(artifact)
        compiler = self._resolve_compiler()
        cmd = [str(compiler), "build", "--ir", str(ir_path), "--out", str(artifact)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise BackendError(f"llvm backend failed: {detail}")
        return BackendBuildResult(backend=self.name, ir_path=ir_path, artifact=artifact)

    def run(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> int:
        result = self.build(ir=ir, ir_path=ir_path, src_path=src_path, out_dir=out_dir, caps=caps)
        cmd = [str(result.artifact)]
        for cap in sorted(caps):
            cmd.extend(["--cap", cap])
        proc = subprocess.run(cmd, capture_output=False)
        return int(proc.returncode)

    def _resolve_compiler(self) -> Path:
        local = shutil.which("nova-llvm")
        if local is not None:
            return Path(local)

        crate = self._crate_dir()
        cargo_cmd = ["cargo", "build", "--release"]
        proc = subprocess.run(cargo_cmd, cwd=crate, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            raise BackendError(f"cannot build compiler/llvm: {detail}")

        exe_name = "nova-llvm.exe" if platform.system().lower().startswith("win") else "nova-llvm"
        built = crate / "target" / "release" / exe_name
        if not built.exists():
            raise BackendError("compiler/llvm build succeeded but nova-llvm binary was not found")
        return built

    def _crate_dir(self) -> Path:
        return Path(__file__).resolve().parents[2] / "compiler" / "llvm"

    def _prepare_artifact_paths(self, artifact: Path) -> None:
        sidecar = artifact.with_name(f"{artifact.name}.ir.json")
        for target in (artifact, sidecar):
            if not target.exists():
                continue
            try:
                target.unlink()
            except PermissionError as exc:
                raise BackendError(f"output file is in use: {target}") from exc
