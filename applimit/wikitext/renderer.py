"""Renderer interface and built-in AST serializers."""

from __future__ import annotations

from typing import Any, Protocol

from applimit.wikitext.ast import ASTNode, Document
from applimit.wikitext.visitor import JsonVisitor, PlainTextVisitor, Visitor


class Renderer(Protocol):
    """Convert AST nodes to an output representation (not HTML)."""

    def render(self, node: ASTNode) -> Any: ...

    def render_document(self, document: Document) -> Any:
        return self.render(document)


class JsonRenderer:
    """Serialize the AST to JSON-compatible dictionaries."""

    def __init__(self) -> None:
        self._visitor = JsonVisitor()

    def render(self, node: ASTNode) -> dict[str, Any]:
        return self._visitor.visit(node)

    def render_document(self, document: Document) -> dict[str, Any]:
        return self.render(document)


class PlainTextRenderer:
    """Extract visible plain text from the AST."""

    def __init__(self) -> None:
        self._visitor = PlainTextVisitor()

    def render(self, node: ASTNode) -> str:
        result = self._visitor.visit(node)
        return result if isinstance(result, str) else str(result)

    def render_document(self, document: Document) -> str:
        return self.render(document)
