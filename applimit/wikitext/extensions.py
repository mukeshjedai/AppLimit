"""Extensible tag and block handlers for the wikitext parser."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Protocol

from applimit.wikitext.ast import ASTNode


class BlockHandler(Protocol):
    def parse_block(self, parser: WikitextParserProtocol, tag: str) -> ASTNode | None: ...


class InlineHandler(Protocol):
    def parse_inline(self, parser: WikitextParserProtocol, tag: str, attrs: dict[str, str]) -> ASTNode | None: ...


class WikitextParserProtocol(Protocol):
    def parse_inline_content(self, stop_at: set[str] | None = None) -> list[ASTNode]: ...

    def parse_template(self) -> ASTNode: ...

    def add_error(self, message: str, raw: str = "") -> ASTNode: ...


BlockHandlerFn = Callable[[WikitextParserProtocol, str], ASTNode | None]
InlineHandlerFn = Callable[[WikitextParserProtocol, str, dict[str, str]], ASTNode | None]


@dataclass
class ExtensionRegistry:
    """Register custom block/inline handlers without modifying parser core."""

    block_tags: dict[str, BlockHandlerFn] = field(default_factory=dict)
    inline_tags: dict[str, InlineHandlerFn] = field(default_factory=dict)
    block_html_tags: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "div",
                "span",
                "p",
                "blockquote",
                "center",
                "gallery",
                "section",
                "table",
                "nowiki",
            }
        )
    )
    inline_html_tags: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "a",
                "abbr",
                "b",
                "big",
                "br",
                "code",
                "em",
                "i",
                "small",
                "span",
                "strong",
                "sub",
                "sup",
                "u",
                "font",
                "kbd",
                "mark",
                "s",
                "del",
                "ins",
            }
        )
    )

    def register_block_tag(self, tag: str, handler: BlockHandlerFn) -> None:
        self.block_tags[tag.lower()] = handler

    def register_inline_tag(self, tag: str, handler: InlineHandlerFn) -> None:
        self.inline_tags[tag.lower()] = handler

    def is_block_html(self, tag: str) -> bool:
        return tag.lower() in self.block_html_tags

    def is_inline_html(self, tag: str) -> bool:
        return tag.lower() in self.inline_html_tags


_ATTR_PATTERN = re.compile(
    r'([a-zA-Z_:][\w:.-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'=<>`]+))',
    re.IGNORECASE,
)


def parse_html_attributes(tag_text: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_PATTERN.finditer(tag_text):
        key = match.group(1).lower()
        value = match.group(2) or match.group(3) or match.group(4) or ""
        attrs[key] = value
    return attrs


def extract_tag_name(tag_text: str) -> str:
    inner = tag_text.strip("<>/ ")
    if not inner:
        return ""
    if inner.startswith("/"):
        inner = inner[1:].strip()
    name = inner.split(None, 1)[0].lower()
    if name.endswith("/"):
        name = name[:-1]
    return name


def default_registry() -> ExtensionRegistry:
    registry = ExtensionRegistry()
    return registry
