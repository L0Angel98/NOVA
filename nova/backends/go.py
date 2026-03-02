from __future__ import annotations

from pathlib import Path
from typing import Set

from nova.ir.nodes import IrMdl

from .base import BackendBuildResult, BackendError


class GoBackend:
    name = "go"

    def build(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> BackendBuildResult:
        raise BackendError("go backend is a v0.1.3 stub; use --b interp or --b llvm")

    def run(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> int:
        raise BackendError("go backend is a v0.1.3 stub; use --b interp or --b llvm")

