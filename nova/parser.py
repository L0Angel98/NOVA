from __future__ import annotations

from typing import Any, Dict, List, Optional

from .lexer import Token, lex
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

UNARY_OPERATORS = {"-", "!"}
ROUTE_METHOD_KEYWORDS = {"GET", "POST", "PUT", "DEL", "PAT", "OPT", "HED", "PATCH", "DELETE"}


class ParseError(ValueError):
    pass


class Parser:
    def __init__(self, tokens: List[Token]) -> None:
        self.tokens = tokens
        self.index = 0

    def parse(self) -> Dict[str, Any]:
        body: List[Dict[str, Any]] = []
        self._consume_statement_terminators()

        while not self._check("EOF"):
            body.append(self._parse_statement())
            self._consume_statement_terminators()

        self._expect("EOF")
        return canonicalize_ast({"type": "Program", "body": body})

    def _parse_statement(self) -> Dict[str, Any]:
        if self._match_keyword("mdl"):
            return self._parse_module_statement()
        if self._match_keyword("imp"):
            return self._parse_import_statement()
        if self._match_keyword("pub"):
            return self._parse_public_statement()
        if self._match_keyword("fn"):
            return self._parse_function_statement()
        if self._match_keyword("let"):
            return self._parse_let_statement()
        if self._match_keyword("if"):
            return self._parse_if_statement()
        if self._match_keyword("grd"):
            return self._parse_guard_statement()
        if self._match_keyword("rte"):
            return self._parse_route_statement()
        if self._match_keyword("tb"):
            return self._parse_table_statement()
        if self._match_keyword("whe"):
            return self._parse_where_statement()
        if self._match_keyword("lim"):
            return self._parse_limit_statement()
        if self._match_keyword("ord"):
            return self._parse_order_statement()
        if self._match_keyword("err"):
            return self._parse_error_statement()
        if self._match_keyword("cap"):
            return self._parse_cap_statement()

        expr = self._parse_expression()
        return {"type": "ExprStmt", "expression": expr}

    def _parse_module_statement(self) -> Dict[str, Any]:
        name = self._expect_ident()
        module_version: Optional[str] = None
        default_result_type: Optional[Dict[str, Any]] = None

        while True:
            self._skip_newlines()
            if self._check_symbol("{"):
                break

            if module_version is None and self._check("IDENT", "v"):
                self._advance()
                version = self._expect("STRING")
                module_version = str(version.value)
                continue

            if default_result_type is None:
                default_result_type = self._parse_type_ref()
                continue

            token = self._current()
            raise self._error_here(
                f"Unexpected token in module signature: {token.type}({token.value})"
            )

        body = self._parse_block()
        return {
            "type": "ModuleDecl",
            "name": name,
            "version": module_version,
            "default_result_type": default_result_type,
            "body": body,
        }

    def _parse_import_statement(self) -> Dict[str, Any]:
        source = self._parse_expression()
        return {"type": "ImportStmt", "source": source}

    def _parse_public_statement(self) -> Dict[str, Any]:
        if self._check_keyword("pub"):
            raise self._error_here("Nested 'pub' is not allowed")
        decl = self._parse_statement()
        return {"type": "PublicDecl", "declaration": decl}

    def _parse_function_statement(self) -> Dict[str, Any]:
        name = self._expect_ident()

        params: List[Dict[str, Any]] = []
        if self._match_symbol("("):
            self._skip_newlines()
            if not self._check_symbol(")"):
                while True:
                    param_name = self._expect_ident()
                    param_annotation: Optional[Dict[str, Any]] = None
                    self._skip_newlines()
                    if self._match_symbol(":"):
                        param_annotation = self._parse_type_ref()
                    params.append(
                        {
                            "type": "Param",
                            "name": param_name,
                            "annotation": param_annotation,
                        }
                    )
                    self._skip_newlines()
                    if not self._match_symbol(","):
                        break
                    self._skip_newlines()
            self._expect_symbol(")")

        return_type: Optional[Dict[str, Any]] = None
        self._skip_newlines()
        if self._match_symbol(":"):
            return_type = self._parse_type_ref()

        body = self._parse_block()
        return {
            "type": "FunctionDecl",
            "name": name,
            "params": params,
            "return_type": return_type,
            "body": body,
        }

    def _parse_let_statement(self) -> Dict[str, Any]:
        name = self._expect_ident()
        annotation: Optional[Dict[str, Any]] = None
        self._skip_newlines()
        if self._match_symbol(":"):
            annotation = self._parse_type_ref()
        self._expect_symbol("=")
        value = self._parse_expression()
        return {"type": "LetStmt", "name": name, "annotation": annotation, "value": value}

    def _parse_if_statement(self) -> Dict[str, Any]:
        condition = self._parse_expression()
        then_body = self._parse_block()

        else_branch: Optional[Dict[str, Any]] = None
        self._skip_newlines()
        if self._match_keyword("els"):
            if self._match_keyword("if"):
                else_branch = {"type": "ElseIf", "branch": self._parse_if_statement()}
            else:
                else_branch = {"type": "ElseBlock", "body": self._parse_block()}

        return {
            "type": "IfStmt",
            "condition": condition,
            "then": then_body,
            "else": else_branch,
        }

    def _parse_guard_statement(self) -> Dict[str, Any]:
        targets: List[Dict[str, Any]] = []
        while True:
            targets.append(self._parse_expression())
            self._skip_newlines()
            if not self._match_symbol(","):
                break
            self._skip_newlines()
        self._expect_symbol(":")
        code = self._parse_expression()
        return {"type": "GuardStmt", "targets": targets, "code": code}

    def _parse_route_statement(self) -> Dict[str, Any]:
        first = self._parse_expression()
        path: Dict[str, Any]
        method: Dict[str, Any]
        fmt: Dict[str, Any] = {"type": "Identifier", "name": "json"}

        self._skip_newlines()
        if self._is_route_method_expr(first):
            method = first
            path = self._parse_expression()
            self._skip_newlines()
            if not self._check_symbol("{") and not self._check_symbol(":"):
                fmt = self._parse_expression()
        else:
            path = first
            method = self._parse_expression()
            self._skip_newlines()
            if not self._check_symbol("{") and not self._check_symbol(":"):
                fmt = self._parse_expression()

        result_type: Optional[Dict[str, Any]] = None
        self._skip_newlines()
        if self._match_symbol(":"):
            result_type = self._parse_type_ref()
        body = self._parse_block()
        return {
            "type": "RouteDecl",
            "path": path,
            "method": method,
            "format": fmt,
            "result_type": result_type,
            "body": body,
        }

    def _parse_table_statement(self) -> Dict[str, Any]:
        target_expr = self._parse_expression()
        table_expr, op = self._normalize_tb_target(target_expr)

        query: List[Dict[str, Any]] = []
        self._skip_newlines()
        if self._match_symbol("{"):
            self._consume_statement_terminators()
            while not self._check_symbol("}"):
                if self._check("EOF"):
                    raise self._error_here("Unterminated tb query block")

                if self._match_keyword("whe"):
                    query.append(self._parse_where_statement())
                elif self._match_keyword("lim"):
                    query.append(self._parse_limit_statement())
                elif self._match_keyword("ord"):
                    query.append(self._parse_order_statement())
                else:
                    token = self._current()
                    raise self._error_here(
                        f"tb query block only allows whe/lim/ord, got {token.type}({token.value})"
                    )
                self._consume_statement_terminators()

            self._expect_symbol("}")

        return {"type": "TableStmt", "table": table_expr, "op": op, "query": query}

    def _parse_where_statement(self) -> Dict[str, Any]:
        condition = self._parse_expression()
        return {"type": "WhereStmt", "condition": condition}

    def _parse_limit_statement(self) -> Dict[str, Any]:
        value = self._parse_expression()
        return {"type": "LimitStmt", "value": value}

    def _parse_order_statement(self) -> Dict[str, Any]:
        field = self._parse_expression()
        direction = self._parse_expression()
        return {"type": "OrderStmt", "field": field, "direction": direction}

    def _parse_error_statement(self) -> Dict[str, Any]:
        value = self._parse_expression()
        return {"type": "ErrorStmt", "value": value}

    def _parse_cap_statement(self) -> Dict[str, Any]:
        value = self._parse_expression()
        return {"type": "CapStmt", "value": value}

    def _parse_block(self) -> List[Dict[str, Any]]:
        self._expect_symbol("{")
        body: List[Dict[str, Any]] = []
        self._consume_statement_terminators()

        while not self._check_symbol("}"):
            if self._check("EOF"):
                raise self._error_here("Unterminated block")
            body.append(self._parse_statement())
            self._consume_statement_terminators()

        self._expect_symbol("}")
        return body

    def _parse_expression(self, min_precedence: int = 1) -> Dict[str, Any]:
        self._skip_newlines()
        left = self._parse_unary()

        while True:
            self._skip_newlines()
            token = self._current()
            if token.type != "SYMBOL" or token.value not in BINARY_PRECEDENCE:
                break

            precedence = BINARY_PRECEDENCE[token.value]
            if precedence < min_precedence:
                break

            op = token.value
            self._advance()
            right = self._parse_expression(precedence + 1)
            left = {
                "type": "BinaryExpr",
                "operator": op,
                "left": left,
                "right": right,
            }

        return left

    def _parse_unary(self) -> Dict[str, Any]:
        self._skip_newlines()

        if self._match_keyword("cap"):
            return {"type": "CapExpr", "expression": self._parse_unary()}

        if self._match_keyword("awt"):
            return {"type": "AwaitExpr", "expression": self._parse_unary()}

        if self._match_keyword("asy"):
            return {"type": "AsyncExpr", "body": self._parse_block()}

        if self._check_symbol_any(UNARY_OPERATORS):
            op = self._current().value
            self._advance()
            return {"type": "UnaryExpr", "operator": op, "expression": self._parse_unary()}

        return self._parse_postfix()

    def _parse_postfix(self) -> Dict[str, Any]:
        expr = self._parse_primary()

        while True:
            self._skip_newlines()
            if self._match_symbol("."):
                name = self._expect_ident()
                expr = {"type": "MemberExpr", "object": expr, "property": name}
                continue

            if self._match_symbol("("):
                args: List[Dict[str, Any]] = []
                self._skip_newlines()
                if not self._check_symbol(")"):
                    while True:
                        args.append(self._parse_expression())
                        self._skip_newlines()
                        if not self._match_symbol(","):
                            break
                        self._skip_newlines()
                self._expect_symbol(")")
                expr = {"type": "CallExpr", "callee": expr, "args": args}
                continue

            break

        return expr

    def _parse_primary(self) -> Dict[str, Any]:
        self._skip_newlines()
        token = self._current()

        if token.type == "STRING":
            self._advance()
            return {"type": "StringLiteral", "value": token.value}

        if token.type == "NUMBER":
            self._advance()
            return {"type": "NumberLiteral", "value": token.value}

        if token.type == "BOOLEAN":
            self._advance()
            return {"type": "BooleanLiteral", "value": token.value}

        if token.type == "NULL":
            self._advance()
            return {"type": "NullLiteral"}

        if token.type == "IDENT":
            self._advance()
            return {"type": "Identifier", "name": token.value}

        if token.type == "KEYWORD" and token.value == "match":
            return self._parse_match_expression()

        if self._match_symbol("("):
            inner = self._parse_expression()
            self._expect_symbol(")")
            return {"type": "ParenExpr", "expression": inner}

        if self._check_symbol("["):
            return self._parse_array_literal()

        if self._check_symbol("{"):
            return self._parse_object_literal()

        raise self._error_here(f"Unexpected token in expression: {token.type} {token.value!r}")

    def _parse_match_expression(self) -> Dict[str, Any]:
        self._expect_keyword("match")
        subject = self._parse_expression()
        self._expect_symbol("{")

        cases: List[Dict[str, Any]] = []
        self._consume_case_separators()
        while not self._check_symbol("}"):
            pattern = self._parse_match_pattern()
            self._expect_symbol("=>")
            value = self._parse_expression()
            cases.append({"type": "MatchCase", "pattern": pattern, "value": value})
            self._consume_case_separators()

        self._expect_symbol("}")
        return {"type": "MatchExpr", "subject": subject, "cases": cases}

    def _parse_match_pattern(self) -> Dict[str, Any]:
        token = self._current()

        if token.type == "IDENT" and token.value == "_":
            self._advance()
            return {"type": "WildcardPattern"}

        if token.type == "STRING":
            self._advance()
            return {
                "type": "LiteralPattern",
                "value": {"type": "StringLiteral", "value": token.value},
            }

        if token.type == "NUMBER":
            self._advance()
            return {
                "type": "LiteralPattern",
                "value": {"type": "NumberLiteral", "value": token.value},
            }

        if token.type == "BOOLEAN":
            self._advance()
            return {
                "type": "LiteralPattern",
                "value": {"type": "BooleanLiteral", "value": token.value},
            }

        if token.type == "NULL":
            self._advance()
            return {"type": "LiteralPattern", "value": {"type": "NullLiteral"}}

        if token.type == "IDENT":
            self._advance()
            return {"type": "IdentifierPattern", "name": token.value}

        return {"type": "ExprPattern", "value": self._parse_expression()}

    def _parse_array_literal(self) -> Dict[str, Any]:
        self._expect_symbol("[")
        items: List[Dict[str, Any]] = []
        self._skip_newlines()

        if not self._check_symbol("]"):
            while True:
                items.append(self._parse_expression())
                self._skip_newlines()
                if not self._match_symbol(","):
                    break
                self._skip_newlines()

        self._expect_symbol("]")
        return {"type": "ArrayLiteral", "items": items}

    def _parse_object_literal(self) -> Dict[str, Any]:
        self._expect_symbol("{")
        fields: List[Dict[str, Any]] = []
        self._skip_newlines()

        if not self._check_symbol("}"):
            while True:
                key = self._parse_object_key()
                self._expect_symbol(":")
                value = self._parse_expression()
                fields.append({"type": "ObjectField", "key": key, "value": value})

                self._skip_newlines()
                if self._match_symbol(","):
                    self._skip_newlines()
                    continue

                if self._check_symbol("}"):
                    break

                if self._is_object_field_start():
                    continue

                raise self._error_here("Expected ',' or next object field")

        self._expect_symbol("}")
        return {"type": "ObjectLiteral", "fields": fields}

    def _parse_object_key(self) -> str:
        token = self._current()
        if token.type == "IDENT":
            self._advance()
            return token.value
        if token.type == "STRING":
            self._advance()
            return token.value
        raise self._error_here("Object key must be identifier or string")

    def _parse_type_ref(self) -> Dict[str, Any]:
        self._skip_newlines()
        name_token = self._current()

        if name_token.type == "IDENT":
            self._advance()
            name = name_token.value
        elif name_token.type == "KEYWORD" and name_token.value in {"mdl", "err"}:
            self._advance()
            name = name_token.value
        else:
            raise self._error_here("Expected type name")

        args: List[Dict[str, Any]] = []
        self._skip_newlines()
        if self._match_symbol("<"):
            self._skip_newlines()
            if self._check_symbol(">"):
                raise self._error_here("Generic type requires at least one argument")

            while True:
                args.append(self._parse_type_ref())
                self._skip_newlines()
                if not self._match_symbol(","):
                    break
                self._skip_newlines()
            self._expect_symbol(">")

        return {"type": "TypeRef", "name": name, "args": args}

    def _normalize_tb_target(self, expr: Dict[str, Any]) -> tuple[Dict[str, Any], Optional[str]]:
        if expr["type"] == "MemberExpr":
            obj = expr["object"]
            prop = expr["property"]
            if obj["type"] == "Identifier" and prop in {"get", "q"}:
                return obj, prop
        return expr, None

    def _is_route_method_expr(self, expr: Dict[str, Any]) -> bool:
        return expr.get("type") == "Identifier" and expr.get("name") in ROUTE_METHOD_KEYWORDS

    def _is_object_field_start(self) -> bool:
        token = self._current()
        if token.type not in {"IDENT", "STRING"}:
            return False
        next_token = self._peek_non_newline(1)
        return next_token.type == "SYMBOL" and next_token.value == ":"

    def _consume_statement_terminators(self) -> None:
        while True:
            if self._match("NEWLINE"):
                continue
            if self._match_symbol(";"):
                continue
            break

    def _consume_case_separators(self) -> None:
        while True:
            if self._match("NEWLINE"):
                continue
            if self._match_symbol(","):
                continue
            if self._match_symbol(";"):
                continue
            break

    def _skip_newlines(self) -> None:
        while self._match("NEWLINE"):
            pass

    def _check(self, typ: str, value: Any = None) -> bool:
        token = self._current()
        if token.type != typ:
            return False
        if value is not None and token.value != value:
            return False
        return True

    def _match(self, typ: str, value: Any = None) -> bool:
        if self._check(typ, value):
            self._advance()
            return True
        return False

    def _check_keyword(self, value: str) -> bool:
        return self._check("KEYWORD", value)

    def _match_keyword(self, value: str) -> bool:
        return self._match("KEYWORD", value)

    def _expect_keyword(self, value: str) -> None:
        if not self._match_keyword(value):
            raise self._error_here(f"Expected keyword '{value}'")

    def _check_symbol(self, value: str) -> bool:
        return self._check("SYMBOL", value)

    def _check_symbol_any(self, values: set[str]) -> bool:
        token = self._current()
        return token.type == "SYMBOL" and token.value in values

    def _match_symbol(self, value: str) -> bool:
        return self._match("SYMBOL", value)

    def _expect_symbol(self, value: str) -> None:
        if not self._match_symbol(value):
            raise self._error_here(f"Expected symbol '{value}'")

    def _expect_ident(self) -> str:
        token = self._current()
        if token.type != "IDENT":
            raise self._error_here("Expected identifier")
        self._advance()
        return token.value

    def _expect(self, typ: str, value: Any = None) -> Token:
        token = self._current()
        if not self._check(typ, value):
            if value is None:
                expected = typ
            else:
                expected = f"{typ}({value})"
            raise self._error_here(f"Expected {expected}, got {token.type}({token.value})")
        self._advance()
        return token

    def _peek_non_newline(self, offset: int = 1) -> Token:
        idx = self.index + offset
        while idx < len(self.tokens) and self.tokens[idx].type == "NEWLINE":
            idx += 1
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def _current(self) -> Token:
        return self.tokens[self.index]

    def _advance(self) -> Token:
        token = self.tokens[self.index]
        if token.type != "EOF":
            self.index += 1
        return token

    def _error_here(self, message: str) -> ParseError:
        token = self._current()
        return ParseError(f"{message} at {token.line}:{token.column}")


def parse_nova(source: str) -> Dict[str, Any]:
    if source.startswith("\ufeff"):
        source = source.lstrip("\ufeff")
    tokens = lex(source)
    return Parser(tokens).parse()


def parse_toon(source: str) -> Any:
    """Parse TOON payloads (table/json/std) into JSON-compatible values."""
    from .toon import ToonDecodeError, decode_toon

    try:
        return decode_toon(source)
    except ToonDecodeError as exc:
        raise ParseError(f"invalid TOON payload: {exc}") from exc
