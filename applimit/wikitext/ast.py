"""Abstract Syntax Tree definitions for MediaWiki wikitext."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceLocation:
    line: int
    column: int
    offset: int

    def to_dict(self) -> dict[str, int]:
        return {"line": self.line, "column": self.column, "offset": self.offset}


def _plain_text(children: list[ASTNode]) -> str | None:
    if not children:
        return ""
    if all(isinstance(child, Text) for child in children):
        return "".join(child.text for child in children)
    return None


def _base_dict(
    node_type: str,
    *,
    children: list[ASTNode] | None = None,
    attributes: dict[str, Any] | None = None,
    location: SourceLocation | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": node_type,
        "children": [child.to_dict() for child in (children or [])],
        "attributes": dict(attributes or {}),
    }
    if location is not None:
        result["location"] = location.to_dict()
    if extra:
        result.update(extra)
    return result


class ASTNode:
    type: str
    children: list[ASTNode]
    attributes: dict[str, Any]
    location: SourceLocation | None

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class Document(ASTNode):
    type: str = "Document"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location)


@dataclass
class Heading(ASTNode):
    level: int
    type: str = "Heading"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {"level": self.level}
        text = _plain_text(self.children)
        if text is not None:
            extra["text"] = text
        return _base_dict(
            self.type,
            children=self.children,
            attributes=self.attributes,
            location=self.location,
            extra=extra,
        )


@dataclass
class Paragraph(ASTNode):
    type: str = "Paragraph"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location)


@dataclass
class Text(ASTNode):
    text: str
    type: str = "Text"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes=self.attributes,
            location=self.location,
            extra={"text": self.text},
        )


@dataclass
class Bold(ASTNode):
    type: str = "Bold"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        text = _plain_text(self.children)
        if text is not None:
            extra["text"] = text
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location, extra=extra)


@dataclass
class Italic(ASTNode):
    type: str = "Italic"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        text = _plain_text(self.children)
        if text is not None:
            extra["text"] = text
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location, extra=extra)


@dataclass
class InternalLink(ASTNode):
    target: str
    type: str = "InternalLink"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "target": self.target},
            location=self.location,
            extra={"target": self.target},
        )


@dataclass
class CategoryLink(ASTNode):
    target: str
    type: str = "CategoryLink"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "target": self.target, "namespace": "Category"},
            location=self.location,
            extra={"target": self.target},
        )


@dataclass
class ExternalLink(ASTNode):
    url: str
    type: str = "ExternalLink"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "url": self.url},
            location=self.location,
            extra={"url": self.url},
        )


@dataclass
class Image(ASTNode):
    target: str
    type: str = "Image"
    options: list[str] = field(default_factory=list)
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "target": self.target, "options": self.options},
            location=self.location,
            extra={"target": self.target, "options": self.options},
        )


File = Image


@dataclass
class Template(ASTNode):
    name: str
    type: str = "Template"
    params: list[TemplateParam] = field(default_factory=list)
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "name": self.name},
            location=self.location,
            extra={"name": self.name, "params": [param.to_dict() for param in self.params]},
        )


@dataclass
class TemplateParam(ASTNode):
    type: str = "TemplateParam"
    name: str | None = None
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if self.name is not None:
            extra["name"] = self.name
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location, extra=extra)


@dataclass
class Reference(ASTNode):
    type: str = "Reference"
    name: str | None = None
    self_closing: bool = False
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {"self_closing": self.self_closing}
        if self.name is not None:
            extra["name"] = self.name
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location, extra=extra)


@dataclass
class ListNode(ASTNode):
    ordered: bool
    type: str = "List"
    items: list[ListItem] = field(default_factory=list)
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        if not self.children:
            self.children = list(self.items)

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.items,
            attributes={**self.attributes, "ordered": self.ordered},
            location=self.location,
            extra={"ordered": self.ordered, "items": [item.to_dict() for item in self.items]},
        )


@dataclass
class ListItem(ASTNode):
    type: str = "ListItem"
    depth: int = 1
    term: bool = False
    marker: str = "*"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={
                **self.attributes,
                "depth": self.depth,
                "term": self.term,
                "marker": self.marker,
            },
            location=self.location,
            extra={"depth": self.depth, "term": self.term, "marker": self.marker},
        )


@dataclass
class Table(ASTNode):
    type: str = "Table"
    rows: list[TableRow] = field(default_factory=list)
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        if not self.children:
            self.children = list(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.rows,
            attributes=self.attributes,
            location=self.location,
            extra={"rows": [row.to_dict() for row in self.rows]},
        )


@dataclass
class TableRow(ASTNode):
    type: str = "TableRow"
    cells: list[TableCell] = field(default_factory=list)
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def __post_init__(self) -> None:
        if not self.children:
            self.children = list(self.cells)

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.cells,
            attributes=self.attributes,
            location=self.location,
            extra={"cells": [cell.to_dict() for cell in self.cells]},
        )


@dataclass
class TableCell(ASTNode):
    type: str = "TableCell"
    header: bool = False
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "header": self.header},
            location=self.location,
            extra={"header": self.header},
        )


@dataclass
class CodeBlock(ASTNode):
    content: str
    type: str = "CodeBlock"
    language: str | None = None
    tag: str = "pre"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {"content": self.content, "tag": self.tag}
        if self.language is not None:
            extra["language"] = self.language
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location, extra=extra)


@dataclass
class Math(ASTNode):
    content: str
    type: str = "Math"
    display: bool = False
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "display": self.display},
            location=self.location,
            extra={"content": self.content, "display": self.display},
        )


@dataclass
class HtmlTag(ASTNode):
    tag: str
    type: str = "HtmlTag"
    void: bool = False
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "tag": self.tag, "void": self.void},
            location=self.location,
            extra={"tag": self.tag, "void": self.void},
        )


@dataclass
class Comment(ASTNode):
    content: str
    type: str = "Comment"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes=self.attributes,
            location=self.location,
            extra={"content": self.content},
        )


@dataclass
class HorizontalRule(ASTNode):
    type: str = "HorizontalRule"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(self.type, children=self.children, attributes=self.attributes, location=self.location)


@dataclass
class Nowiki(ASTNode):
    content: str
    type: str = "Nowiki"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes=self.attributes,
            location=self.location,
            extra={"content": self.content},
        )


@dataclass
class MagicWord(ASTNode):
    name: str
    type: str = "MagicWord"
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "name": self.name},
            location=self.location,
            extra={"name": self.name},
        )


@dataclass
class ParseError(ASTNode):
    message: str
    type: str = "ParseError"
    raw: str = ""
    recovered: bool = True
    children: list[ASTNode] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    location: SourceLocation | None = None

    def to_dict(self) -> dict[str, Any]:
        return _base_dict(
            self.type,
            children=self.children,
            attributes={**self.attributes, "recovered": self.recovered},
            location=self.location,
            extra={"message": self.message, "raw": self.raw, "recovered": self.recovered},
        )
