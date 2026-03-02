from __future__ import annotations

from .base import Backend, BackendBuildResult, BackendError
from .go import GoBackend
from .interp import InterpBackend
from .llvm import LlvmBackend


def get_backend(name: str) -> Backend:
    normalized = (name or "interp").strip().lower()
    if normalized == "interp":
        return InterpBackend()
    if normalized == "llvm":
        return LlvmBackend()
    if normalized == "go":
        return GoBackend()
    raise BackendError(f"unsupported backend '{name}' (expected: llvm|go|interp)")


__all__ = [
    "Backend",
    "BackendBuildResult",
    "BackendError",
    "get_backend",
    "InterpBackend",
    "LlvmBackend",
    "GoBackend",
]

