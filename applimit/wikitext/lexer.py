"""Character-level lexer for MediaWiki wikitext."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from applimit.wikitext.ast import SourceLocation


def location_at(text: str, pos: int) -> SourceLocation:
    line = text.count("\n", 0, pos) + 1
    last_nl = text.rfind("\n", 0, pos)
    column = pos + 1 if last_nl == -1 else pos - last_nl
    return SourceLocation(line=line, column=column, offset=pos)


def normalize_wikitext(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


class TokenKind(Enum):
    EOF = auto()
    TEXT = auto()
    NEWLINE = auto()
    EQUALS = auto()
    STAR = auto()
    HASH = auto()
    SEMICOLON = auto()
    COLON = auto()
    PIPE = auto()
    BANG = auto()
    TABLE_START = auto()
    TABLE_END = auto()
    TABLE_ROW = auto()
    WIKI_LINK_OPEN = auto()
    WIKI_LINK_CLOSE = auto()
    TEMPLATE_OPEN = auto()
    TEMPLATE_CLOSE = auto()
    EXT_LINK_OPEN = auto()
    EXT_LINK_CLOSE = auto()
    APOSTROPHE = auto()
    HTML_OPEN = auto()
    HTML_CLOSE = auto()
    HTML_VOID = auto()
    COMMENT = auto()


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    value: str
    pos: int


class SourceReader:
    """Efficient cursor over wikitext source."""

    __slots__ = ("text", "pos", "length")

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.length = len(text)

    def at_end(self) -> bool:
        return self.pos >= self.length

    def peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        if index >= self.length:
            return ""
        return self.text[index]

    def slice(self, start: int, end: int) -> str:
        return self.text[start:end]

    def advance(self, count: int = 1) -> None:
        self.pos = min(self.pos + count, self.length)

    def line_start(self) -> bool:
        if self.pos == 0:
            return True
        return self.text[self.pos - 1] == "\n"

    def current_line(self) -> tuple[int, int]:
        if self.pos >= self.length:
            return self.length, self.length
        line_start = self.text.rfind("\n", 0, self.pos) + 1
        line_end = self.text.find("\n", self.pos)
        if line_end == -1:
            line_end = self.length
        if self.text[self.pos] == "\n":
            line_start = self.pos + 1
            line_end = self.text.find("\n", line_start)
            if line_end == -1:
                line_end = self.length
        return line_start, line_end

    def line_text(self) -> str:
        start, end = self.current_line()
        return self.text[start:end]

    def location_at(self, pos: int | None = None) -> SourceLocation:
        return location_at(self.text, self.pos if pos is None else pos)


class Lexer:
    """Tokenize wikitext into a flat stream for the parser."""

    _HTML_VOID_TAGS = frozenset(
        {
            "br",
            "hr",
            "img",
            "meta",
            "link",
            "input",
            "area",
            "base",
            "col",
            "embed",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self.reader = SourceReader(normalized)

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        reader = self.reader
        while not reader.at_end():
            pos = reader.pos
            ch = reader.peek()

            if ch == "\n":
                tokens.append(Token(TokenKind.NEWLINE, "\n", pos))
                reader.advance()
                continue

            if ch == "=" and reader.line_start():
                count = self._consume_run("=")
                tokens.append(Token(TokenKind.EQUALS, "=" * count, pos))
                continue

            if ch == "{" and reader.peek(1) == "|":
                reader.advance(2)
                tokens.append(Token(TokenKind.TABLE_START, "{|", pos))
                continue

            if ch == "|" and reader.peek(1) == "}":
                reader.advance(2)
                tokens.append(Token(TokenKind.TABLE_END, "|}", pos))
                continue

            if ch == "|" and reader.peek(1) == "-":
                reader.advance(2)
                tokens.append(Token(TokenKind.TABLE_ROW, "|-", pos))
                continue

            if ch == "[" and reader.peek(1) == "[":
                reader.advance(2)
                tokens.append(Token(TokenKind.WIKI_LINK_OPEN, "[[", pos))
                continue

            if ch == "]" and reader.peek(1) == "]":
                reader.advance(2)
                tokens.append(Token(TokenKind.WIKI_LINK_CLOSE, "]]", pos))
                continue

            if ch == "{" and reader.peek(1) == "{":
                reader.advance(2)
                tokens.append(Token(TokenKind.TEMPLATE_OPEN, "{{", pos))
                continue

            if ch == "}" and reader.peek(1) == "}":
                reader.advance(2)
                tokens.append(Token(TokenKind.TEMPLATE_CLOSE, "}}", pos))
                continue

            if ch == "[" and reader.peek(1) != "[":
                reader.advance()
                tokens.append(Token(TokenKind.EXT_LINK_OPEN, "[", pos))
                continue

            if ch == "]":
                reader.advance()
                tokens.append(Token(TokenKind.EXT_LINK_CLOSE, "]", pos))
                continue

            if ch == "'":
                count = self._consume_run("'")
                tokens.append(Token(TokenKind.APOSTROPHE, "'" * count, pos))
                continue

            if ch == "<":
                html_token = self._try_html_token(pos)
                if html_token is not None:
                    tokens.append(html_token)
                    continue

            if ch == "*" and reader.line_start():
                reader.advance()
                tokens.append(Token(TokenKind.STAR, "*", pos))
                continue

            if ch == "#" and reader.line_start():
                reader.advance()
                tokens.append(Token(TokenKind.HASH, "#", pos))
                continue

            if ch == ";" and reader.line_start():
                reader.advance()
                tokens.append(Token(TokenKind.SEMICOLON, ";", pos))
                continue

            if ch == ":" and reader.line_start():
                reader.advance()
                tokens.append(Token(TokenKind.COLON, ":", pos))
                continue

            if ch == "!" and reader.line_start():
                reader.advance()
                tokens.append(Token(TokenKind.BANG, "!", pos))
                continue

            if ch == "|" and reader.line_start():
                reader.advance()
                tokens.append(Token(TokenKind.PIPE, "|", pos))
                continue

            if ch == "|":
                reader.advance()
                tokens.append(Token(TokenKind.PIPE, "|", pos))
                continue

            if ch == "#":
                reader.advance()
                tokens.append(Token(TokenKind.HASH, "#", pos))
                continue

            if ch == "*":
                reader.advance()
                tokens.append(Token(TokenKind.STAR, "*", pos))
                continue

            if ch == ";":
                reader.advance()
                tokens.append(Token(TokenKind.SEMICOLON, ";", pos))
                continue

            if ch == ":":
                reader.advance()
                tokens.append(Token(TokenKind.COLON, ":", pos))
                continue

            if ch == "!":
                reader.advance()
                tokens.append(Token(TokenKind.BANG, "!", pos))
                continue

            start = reader.pos
            reader.advance()
            while not reader.at_end():
                nxt = reader.peek()
                if nxt == "\n":
                    break
                if self._is_special_start(reader):
                    break
                reader.advance()
            tokens.append(Token(TokenKind.TEXT, reader.slice(start, reader.pos), start))

        tokens.append(Token(TokenKind.EOF, "", reader.pos))
        return tokens

    def _consume_run(self, char: str) -> int:
        count = 0
        while self.reader.peek() == char:
            self.reader.advance()
            count += 1
        return count

    def _is_special_start(self, reader: SourceReader) -> bool:
        ch = reader.peek()
        if ch == "'":
            return True
        if ch == "[":
            return True
        if ch == "{" and reader.peek(1) in "{|":
            return True
        if ch == "}" and reader.peek(1) == "}":
            return True
        if ch == "]":
            return True
        if ch == "|" and reader.peek(1) in "-}":
            return True
        if ch == "<":
            return True
        return False

    def _try_html_token(self, pos: int) -> Token | None:
        reader = self.reader
        if reader.peek(1) == "!" and reader.peek(2) == "-" and reader.peek(3) == "-":
            end = reader.text.find("-->", reader.pos + 4)
            if end == -1:
                return None
            value = reader.slice(reader.pos, end + 3)
            reader.pos = end + 3
            return Token(TokenKind.COMMENT, value, pos)

        if reader.peek(1) == "/":
            end = reader.text.find(">", reader.pos + 2)
            if end == -1:
                return None
            value = reader.slice(reader.pos, end + 1)
            reader.pos = end + 1
            return Token(TokenKind.HTML_CLOSE, value, pos)

        end = reader.text.find(">", reader.pos + 1)
        if end == -1:
            return None
        tag_text = reader.slice(reader.pos, end + 1)
        reader.pos = end + 1
        tag_name = self._extract_tag_name(tag_text)
        if tag_text.rstrip().endswith("/>") or tag_name in self._HTML_VOID_TAGS:
            return Token(TokenKind.HTML_VOID, tag_text, pos)
        return Token(TokenKind.HTML_OPEN, tag_text, pos)

    @staticmethod
    def _extract_tag_name(tag_text: str) -> str:
        inner = tag_text.strip("<>/ ")
        name = inner.split(None, 1)[0].lower()
        if name.endswith("/"):
            name = name[:-1]
        return name


# normalize_wikitext moved above SourceLocation import block
