from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

CANONICAL_KEYWORDS = {
    "fn",
    "let",
    "if",
    "els",
    "match",
    "grd",
    "rte",
    "tb",
    "whe",
    "lim",
    "ord",
    "asy",
    "awt",
    "imp",
    "pub",
    "mdl",
    "err",
    "cap",
}

ALIAS_KEYWORDS = {
    "function": "fn",
    "else": "els",
    "guard": "grd",
    "route": "rte",
    "table": "tb",
    "where": "whe",
    "limit": "lim",
    "order": "ord",
    "async": "asy",
    "await": "awt",
    "import": "imp",
    "public": "pub",
    "module": "mdl",
    "error": "err",
    "capability": "cap",
    "capabilities": "cap",
    "true": "tru",
    "false": "fal",
    "null": "nul",
}

MULTI_CHAR_SYMBOLS = {"==", "!=", "<=", ">=", "&&", "||", "=>"}
SINGLE_CHAR_SYMBOLS = {"{", "}", "[", "]", "(", ")", ",", ":", ";", ".", "=", "+", "-", "*", "/", "<", ">", "!"}


@dataclass(frozen=True)
class Token:
    type: str
    value: Any
    line: int
    column: int


class LexError(ValueError):
    pass


class Lexer:
    def __init__(self, source: str) -> None:
        self.source = source
        self.index = 0
        self.line = 1
        self.column = 1

    def lex(self) -> List[Token]:
        tokens: List[Token] = []
        while not self._is_eof():
            ch = self._peek()

            if ch in " \t\r":
                self._advance()
                continue

            if ch == "\n":
                tokens.append(self._make_token("NEWLINE", "\n"))
                self._advance_newline()
                continue

            if ch == "#":
                self._skip_line_comment()
                continue

            if ch == "/" and self._peek(1) == "/":
                self._skip_line_comment()
                continue

            if ch == "/" and self._peek(1) == "*":
                self._skip_block_comment()
                continue

            if self.source.startswith('str"', self.index):
                tokens.append(self._lex_string(prefixed=True))
                continue

            if ch == '"':
                tokens.append(self._lex_string(prefixed=False))
                continue

            if self.source.startswith("num", self.index) and self._is_number_start_after_num():
                tokens.append(self._lex_number(prefixed=True))
                continue

            if ch.isdigit():
                tokens.append(self._lex_number(prefixed=False))
                continue

            if ch.isalpha() or ch == "_":
                tokens.append(self._lex_identifier_or_keyword())
                continue

            two = ch + self._peek(1)
            if two in MULTI_CHAR_SYMBOLS:
                tokens.append(self._make_token("SYMBOL", two))
                self._advance()
                self._advance()
                continue

            if ch in SINGLE_CHAR_SYMBOLS:
                tokens.append(self._make_token("SYMBOL", ch))
                self._advance()
                continue

            raise LexError(f"Unexpected character '{ch}' at {self.line}:{self.column}")

        tokens.append(self._make_token("EOF", None))
        return tokens

    def _lex_identifier_or_keyword(self) -> Token:
        start_line = self.line
        start_col = self.column

        text = []
        while not self._is_eof() and (self._peek().isalnum() or self._peek() == "_"):
            text.append(self._peek())
            self._advance()

        raw = "".join(text)
        canonical = ALIAS_KEYWORDS.get(raw, raw)

        if canonical == "tru":
            return Token("BOOLEAN", True, start_line, start_col)
        if canonical == "fal":
            return Token("BOOLEAN", False, start_line, start_col)
        if canonical == "nul":
            return Token("NULL", None, start_line, start_col)
        if canonical in CANONICAL_KEYWORDS:
            return Token("KEYWORD", canonical, start_line, start_col)
        return Token("IDENT", raw, start_line, start_col)

    def _lex_string(self, prefixed: bool) -> Token:
        start_line = self.line
        start_col = self.column

        if prefixed:
            self._advance()  # s
            self._advance()  # t
            self._advance()  # r

        self._expect_char('"')

        chars: List[str] = []
        while not self._is_eof():
            ch = self._peek()
            if ch == '"':
                self._advance()
                return Token("STRING", "".join(chars), start_line, start_col)
            if ch == "\\":
                self._advance()
                if self._is_eof():
                    raise LexError(f"Unterminated string at {start_line}:{start_col}")
                esc = self._peek()
                self._advance()
                chars.append(self._decode_escape(esc, start_line, start_col))
                continue
            if ch == "\n":
                raise LexError(f"Unterminated string at {start_line}:{start_col}")
            chars.append(ch)
            self._advance()

        raise LexError(f"Unterminated string at {start_line}:{start_col}")

    def _lex_number(self, prefixed: bool) -> Token:
        start_line = self.line
        start_col = self.column

        if prefixed:
            self._advance()
            self._advance()
            self._advance()

        raw = []
        if self._peek() in "+-":
            raw.append(self._peek())
            self._advance()

        digit_count = 0
        while not self._is_eof() and self._peek().isdigit():
            raw.append(self._peek())
            self._advance()
            digit_count += 1

        if not self._is_eof() and self._peek() == ".":
            raw.append(".")
            self._advance()
            while not self._is_eof() and self._peek().isdigit():
                raw.append(self._peek())
                self._advance()
                digit_count += 1

        if digit_count == 0:
            raise LexError(f"Invalid number literal at {start_line}:{start_col}")

        return Token("NUMBER", "".join(raw), start_line, start_col)

    def _is_number_start_after_num(self) -> bool:
        pos = self.index + 3
        if pos >= len(self.source):
            return False
        ch = self.source[pos]
        if ch in "+-":
            pos += 1
            if pos >= len(self.source):
                return False
            ch = self.source[pos]
        return ch.isdigit()

    def _decode_escape(self, esc: str, line: int, column: int) -> str:
        mapping = {
            '"': '"',
            "\\": "\\",
            "n": "\n",
            "r": "\r",
            "t": "\t",
        }
        if esc not in mapping:
            raise LexError(f"Invalid escape \\{esc} at {line}:{column}")
        return mapping[esc]

    def _skip_line_comment(self) -> None:
        while not self._is_eof() and self._peek() != "\n":
            self._advance()

    def _skip_block_comment(self) -> None:
        self._advance()  # /
        self._advance()  # *
        while not self._is_eof():
            if self._peek() == "*" and self._peek(1) == "/":
                self._advance()
                self._advance()
                return
            if self._peek() == "\n":
                self._advance_newline()
            else:
                self._advance()
        raise LexError(f"Unterminated block comment at {self.line}:{self.column}")

    def _expect_char(self, char: str) -> None:
        if self._peek() != char:
            raise LexError(f"Expected '{char}' at {self.line}:{self.column}")
        self._advance()

    def _make_token(self, typ: str, value: Any) -> Token:
        return Token(typ, value, self.line, self.column)

    def _peek(self, offset: int = 0) -> str:
        pos = self.index + offset
        if pos >= len(self.source):
            return "\0"
        return self.source[pos]

    def _advance(self) -> None:
        if self._is_eof():
            return
        if self.source[self.index] == "\n":
            self._advance_newline()
            return
        self.index += 1
        self.column += 1

    def _advance_newline(self) -> None:
        self.index += 1
        self.line += 1
        self.column = 1

    def _is_eof(self) -> bool:
        return self.index >= len(self.source)


def lex(source: str) -> List[Token]:
    return Lexer(source).lex()
