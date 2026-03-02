from __future__ import annotations

from typing import Any, Dict, List

from .ast_utils import canonicalize_ast

BINARY_PRECEDENCE = {
    "||": 1,
    "&&": 2,
    "==": 3,
    "!=": 3,
    "<": 4,
    "<=": 4,
    ">": 4,
    ">=": 4,
    "+": 5,
    "-": 5,
    "*": 6,
    "/": 6,
}


class Formatter:
    def __init__(self, indent: str = "  ") -> None:
        self.indent = indent

    def format_program(self, ast: Dict[str, Any]) -> str:
        ast = canonicalize_ast(ast)
        body = ast.get("body", [])

        lines: List[str] = []
        for stmt in body:
            lines.extend(self._format_statement_lines(stmt, 0))

        return "\n".join(lines).rstrip() + "\n"

    def _format_statement_lines(self, stmt: Dict[str, Any], level: int) -> List[str]:
        typ = stmt["type"]
        ind = self.indent * level

        if typ == "ModuleDecl":
            header = f"{ind}mdl {stmt['name']}"
            if stmt.get("version"):
                header = f'{header} v"{self._escape_string(stmt["version"])}"'
            if stmt.get("default_result_type") is not None:
                header = f"{header} {self._format_type_ref(stmt['default_result_type'])}"
            return self._format_header_block(
                header,
                stmt.get("body", []),
                level,
            )

        if typ == "ImportStmt":
            return [f"{ind}imp {self._format_expr(stmt['source'])}"]

        if typ == "PublicDecl":
            decl_lines = self._format_statement_lines(stmt["declaration"], level)
            first = decl_lines[0]
            decl_lines[0] = f"{ind}pub {first[len(ind):]}"
            return decl_lines

        if typ == "FunctionDecl":
            params = ", ".join(self._format_param(param) for param in stmt.get("params", []))
            return_type = ""
            if stmt.get("return_type") is not None:
                return_type = f": {self._format_type_ref(stmt['return_type'])}"
            return self._format_header_block(
                f"{ind}fn {stmt['name']}({params}){return_type}",
                stmt.get("body", []),
                level,
            )

        if typ == "LetStmt":
            annotation = ""
            if stmt.get("annotation") is not None:
                annotation = f": {self._format_type_ref(stmt['annotation'])}"
            return [f"{ind}let {stmt['name']}{annotation} = {self._format_expr(stmt['value'])}"]

        if typ == "IfStmt":
            return self._format_if_lines(stmt, level, "if")

        if typ == "GuardStmt":
            targets = ", ".join(self._format_expr(expr) for expr in stmt.get("targets", []))
            code = self._format_expr(stmt["code"])
            return [f"{ind}grd {targets} : {code}"]

        if typ == "RouteDecl":
            path = self._format_expr(stmt["path"])
            method = self._format_expr(stmt["method"])
            fmt = self._format_expr(stmt["format"])
            result_type = ""
            if stmt.get("result_type") is not None:
                result_type = f": {self._format_type_ref(stmt['result_type'])}"
            return self._format_header_block(
                f"{ind}rte {path} {method} {fmt}{result_type}",
                stmt.get("body", []),
                level,
            )

        if typ == "TableStmt":
            head = f"{ind}tb {self._format_expr(stmt['table'])}"
            op = stmt.get("op")
            if op is not None:
                head = f"{head}.{op}"
            query = stmt.get("query", [])
            if query:
                lines = [f"{head} {{"]
                for clause in query:
                    lines.extend(self._format_statement_lines(clause, level + 1))
                lines.append(f"{ind}}}")
                return lines
            return [head]

        if typ == "WhereStmt":
            return [f"{ind}whe {self._format_expr(stmt['condition'])}"]

        if typ == "LimitStmt":
            return [f"{ind}lim {self._format_expr(stmt['value'])}"]

        if typ == "OrderStmt":
            field = self._format_expr(stmt["field"])
            direction = self._format_expr(stmt["direction"])
            return [f"{ind}ord {field} {direction}"]

        if typ == "ErrorStmt":
            return [f"{ind}err {self._format_expr(stmt['value'])}"]

        if typ == "CapStmt":
            return [f"{ind}cap {self._format_expr(stmt['value'])}"]

        if typ == "ExprStmt":
            return [f"{ind}{self._format_expr(stmt['expression'])}"]

        raise ValueError(f"Unsupported statement type in formatter: {typ}")

    def _format_param(self, param: Any) -> str:
        if isinstance(param, str):
            return param
        name = param["name"]
        annotation = param.get("annotation")
        if annotation is None:
            return name
        return f"{name}: {self._format_type_ref(annotation)}"

    def _format_type_ref(self, type_ref: Dict[str, Any]) -> str:
        name = type_ref["name"]
        args = type_ref.get("args", [])
        if not args:
            return name
        rendered_args = ", ".join(self._format_type_ref(arg) for arg in args)
        return f"{name}<{rendered_args}>"

    def _format_if_lines(self, stmt: Dict[str, Any], level: int, keyword: str) -> List[str]:
        ind = self.indent * level
        cond = self._format_expr(stmt["condition"])
        lines = [f"{ind}{keyword} {cond} {{"]
        for inner in stmt.get("then", []):
            lines.extend(self._format_statement_lines(inner, level + 1))
        lines.append(f"{ind}}}")

        else_branch = stmt.get("else")
        if else_branch is None:
            return lines

        if else_branch["type"] == "ElseBlock":
            lines.append(f"{ind}els {{")
            for inner in else_branch.get("body", []):
                lines.extend(self._format_statement_lines(inner, level + 1))
            lines.append(f"{ind}}}")
            return lines

        if else_branch["type"] == "ElseIf":
            lines.extend(self._format_if_lines(else_branch["branch"], level, "els if"))
            return lines

        raise ValueError(f"Unsupported else branch type: {else_branch['type']}")

    def _format_header_block(self, header: str, body: List[Dict[str, Any]], level: int) -> List[str]:
        ind = self.indent * level
        lines = [f"{header} {{"]
        for stmt in body:
            lines.extend(self._format_statement_lines(stmt, level + 1))
        lines.append(f"{ind}}}")
        return lines

    def _format_expr(self, expr: Dict[str, Any], parent_precedence: int = 0) -> str:
        typ = expr["type"]

        if typ == "Identifier":
            return expr["name"]

        if typ == "StringLiteral":
            # v1 update: canonical string literals no longer require str-prefix.
            return f'"{self._escape_string(expr["value"])}"'

        if typ == "NumberLiteral":
            return f"num{expr['value']}"

        if typ == "BooleanLiteral":
            return "tru" if expr["value"] else "fal"

        if typ == "NullLiteral":
            return "nul"

        if typ == "ArrayLiteral":
            items = ", ".join(self._format_expr(item) for item in expr.get("items", []))
            return f"[{items}]"

        if typ == "ObjectLiteral":
            fields = expr.get("fields", [])
            rendered = ", ".join(
                f"{field['key']}: {self._format_expr(field['value'])}" for field in fields
            )
            return f"{{{rendered}}}"

        if typ == "MemberExpr":
            text = f"{self._format_expr(expr['object'], 8)}.{expr['property']}"
            return f"({text})" if 8 < parent_precedence else text

        if typ == "CallExpr":
            args = ", ".join(self._format_expr(arg) for arg in expr.get("args", []))
            text = f"{self._format_expr(expr['callee'], 8)}({args})"
            return f"({text})" if 8 < parent_precedence else text

        if typ == "UnaryExpr":
            text = f"{expr['operator']}{self._format_expr(expr['expression'], 7)}"
            return f"({text})" if 7 < parent_precedence else text

        if typ == "AwaitExpr":
            text = f"awt {self._format_expr(expr['expression'], 7)}"
            return f"({text})" if 7 < parent_precedence else text

        if typ == "AsyncExpr":
            if not expr.get("body"):
                return "asy {}"
            body = "; ".join(self._format_inline_stmt(stmt) for stmt in expr["body"])
            return f"asy {{ {body} }}"

        if typ == "MatchExpr":
            cases = ", ".join(
                f"{self._format_pattern(case['pattern'])} => {self._format_expr(case['value'])}"
                for case in expr.get("cases", [])
            )
            text = f"match {self._format_expr(expr['subject'])} {{ {cases} }}"
            return f"({text})" if parent_precedence > 0 else text

        if typ == "BinaryExpr":
            op = expr["operator"]
            precedence = BINARY_PRECEDENCE[op]
            left = self._format_expr(expr["left"], precedence)
            right = self._format_expr(expr["right"], precedence + 1)
            text = f"{left} {op} {right}"
            return f"({text})" if precedence < parent_precedence else text

        raise ValueError(f"Unsupported expression type in formatter: {typ}")

    def _format_pattern(self, pattern: Dict[str, Any]) -> str:
        typ = pattern["type"]

        if typ == "WildcardPattern":
            return "_"

        if typ == "LiteralPattern":
            return self._format_expr(pattern["value"])

        if typ == "IdentifierPattern":
            return pattern["name"]

        if typ == "ExprPattern":
            return self._format_expr(pattern["value"])

        raise ValueError(f"Unsupported pattern type in formatter: {typ}")

    def _format_inline_stmt(self, stmt: Dict[str, Any]) -> str:
        lines = self._format_statement_lines(stmt, 0)
        collapsed = " ".join(" ".join(lines).split())
        return collapsed

    @staticmethod
    def _escape_string(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )


def format_nova(ast: Dict[str, Any]) -> str:
    return Formatter().format_program(ast)
