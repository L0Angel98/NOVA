"""NOVA v0.1 parser, formatter, checker and runtime package."""

from .checker import check_ast
from .db_ir import DbIr, DbPlan, InMemoryDbIrAdapter, build_ir_from_table_stmt, compile_plan
from .formatter import format_nova
from .parser import parse_nova
from .runtime import NovaRuntime, run_server
from .toon import decode_toon, encode_toon
from .agent_context import check_agent, pack_agent, sync_agent
from .version import VERSION

__version__ = VERSION

__all__ = [
    "VERSION",
    "__version__",
    "parse_nova",
    "format_nova",
    "check_ast",
    "sync_agent",
    "pack_agent",
    "check_agent",
    "DbIr",
    "DbPlan",
    "InMemoryDbIrAdapter",
    "build_ir_from_table_stmt",
    "compile_plan",
    "NovaRuntime",
    "run_server",
    "encode_toon",
    "decode_toon",
]
