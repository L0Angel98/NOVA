from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Union


@dataclass(frozen=True)
class IrJson:
    k: str = "json"
    v: Any = None


@dataclass(frozen=True)
class IrId:
    k: str = "id"
    n: str = ""


@dataclass(frozen=True)
class IrObj:
    k: str = "obj"
    f: Dict[str, "IrExpr"] = field(default_factory=dict)


@dataclass(frozen=True)
class IrArr:
    k: str = "arr"
    i: List["IrExpr"] = field(default_factory=list)


@dataclass(frozen=True)
class IrCall:
    k: str = "call"
    fn: str = ""
    a: List["IrExpr"] = field(default_factory=list)


IrExpr = Union[IrJson, IrId, IrObj, IrArr, IrCall]


@dataclass(frozen=True)
class IrLet:
    k: str = "let"
    n: str = ""
    v: IrExpr = field(default_factory=IrJson)


@dataclass(frozen=True)
class IrCap:
    k: str = "cap"
    c: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class IrGrd:
    k: str = "grd"
    t: List["IrExpr"] = field(default_factory=list)
    c: "IrExpr" = field(default_factory=IrJson)


@dataclass(frozen=True)
class IrRstOk:
    k: str = "rst.ok"
    v: IrExpr = field(default_factory=IrJson)


@dataclass(frozen=True)
class IrRstErr:
    k: str = "rst.err"
    v: IrExpr = field(default_factory=IrJson)


IrStmt = Union[IrLet, IrCap, IrGrd, IrCall, IrRstOk, IrRstErr]


@dataclass(frozen=True)
class IrRte:
    k: str = "rte"
    m: str = "GET"
    p: str = "/"
    f: str = "json"
    b: List[IrStmt] = field(default_factory=list)


@dataclass(frozen=True)
class IrMdl:
    k: str = "mdl"
    irv: str = "0.1.4"
    n: str = "main"
    v: str = "0.1.4"
    rte: List[IrRte] = field(default_factory=list)
    b: List[IrStmt] = field(default_factory=list)
