from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Set

from nova.ir.nodes import IrMdl


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendBuildResult:
    backend: str
    ir_path: Path
    artifact: Path


class Backend(Protocol):
    name: str

    def build(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> BackendBuildResult:
        raise NotImplementedError

    def run(self, *, ir: IrMdl, ir_path: Path, src_path: Path, out_dir: Path, caps: Set[str]) -> int:
        raise NotImplementedError

