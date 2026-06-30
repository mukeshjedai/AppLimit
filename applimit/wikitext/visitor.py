"""Visitor pattern for wikitext AST traversal and rendering."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from applimit.wikitext.ast import (
    ASTNode,
    Bold,
    CategoryLink,
    CodeBlock,
    Comment,
    Document,
    ExternalLink,
    Heading,
    HorizontalRule,
    HtmlTag,
    Image,
    InternalLink,
    Italic,
    ListItem,
    ListNode,
    MagicWord,
    Math,
    Nowiki,
    Paragraph,
    ParseError,
    Reference,
    Table,
    TableCell,
    TableRow,
    Template,
    TemplateParam,
    Text,
)


class Visitor(ABC):
    """Walk an AST without coupling to a specific output format."""

    def visit(self, node: ASTNode) -> Any:
        method = getattr(self, f"visit_{node.type}", self.visit_unknown)
        return method(node)

    def visit_children(self, node: ASTNode) -> list[Any]:
        return [self.visit(child) for child in node.children]

    @abstractmethod
    def visit_unknown(self, node: ASTNode) -> Any:
        raise NotImplementedError

    def visit_Document(self, node: Document) -> Any:
        return self.visit_unknown(node)

    def visit_Heading(self, node: Heading) -> Any:
        return self.visit_unknown(node)

    def visit_Paragraph(self, node: Paragraph) -> Any:
        return self.visit_unknown(node)

    def visit_Text(self, node: Text) -> Any:
        return self.visit_unknown(node)

    def visit_Bold(self, node: Bold) -> Any:
        return self.visit_unknown(node)

    def visit_Italic(self, node: Italic) -> Any:
        return self.visit_unknown(node)

    def visit_InternalLink(self, node: InternalLink) -> Any:
        return self.visit_unknown(node)

    def visit_CategoryLink(self, node: CategoryLink) -> Any:
        return self.visit_unknown(node)

    def visit_ExternalLink(self, node: ExternalLink) -> Any:
        return self.visit_unknown(node)

    def visit_Image(self, node: Image) -> Any:
        return self.visit_unknown(node)

    def visit_Template(self, node: Template) -> Any:
        return self.visit_unknown(node)

    def visit_TemplateParam(self, node: TemplateParam) -> Any:
        return self.visit_unknown(node)

    def visit_Reference(self, node: Reference) -> Any:
        return self.visit_unknown(node)

    def visit_List(self, node: ListNode) -> Any:
        return self.visit_unknown(node)

    def visit_ListItem(self, node: ListItem) -> Any:
        return self.visit_unknown(node)

    def visit_Table(self, node: Table) -> Any:
        return self.visit_unknown(node)

    def visit_TableRow(self, node: TableRow) -> Any:
        return self.visit_unknown(node)

    def visit_TableCell(self, node: TableCell) -> Any:
        return self.visit_unknown(node)

    def visit_CodeBlock(self, node: CodeBlock) -> Any:
        return self.visit_unknown(node)

    def visit_Math(self, node: Math) -> Any:
        return self.visit_unknown(node)

    def visit_HtmlTag(self, node: HtmlTag) -> Any:
        return self.visit_unknown(node)

    def visit_Comment(self, node: Comment) -> Any:
        return self.visit_unknown(node)

    def visit_HorizontalRule(self, node: HorizontalRule) -> Any:
        return self.visit_unknown(node)

    def visit_Nowiki(self, node: Nowiki) -> Any:
        return self.visit_unknown(node)

    def visit_MagicWord(self, node: MagicWord) -> Any:
        return self.visit_unknown(node)

    def visit_ParseError(self, node: ParseError) -> Any:
        return self.visit_unknown(node)


class JsonVisitor(Visitor):
    """Serialize AST nodes to JSON-compatible dictionaries."""

    def visit_unknown(self, node: ASTNode) -> dict[str, Any]:
        return node.to_dict()

    def visit_Document(self, node: Document) -> dict[str, Any]:
        return node.to_dict()

    def visit_Template(self, node: Template) -> dict[str, Any]:
        return node.to_dict()

    def visit_List(self, node: ListNode) -> dict[str, Any]:
        return node.to_dict()

    def visit_Table(self, node: Table) -> dict[str, Any]:
        return node.to_dict()


class PlainTextVisitor(Visitor):
    """Extract visible text from the AST."""

    def visit_unknown(self, node: ASTNode) -> str:
        return ""

    def visit_Document(self, node: Document) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Text(self, node: Text) -> str:
        return node.text

    def visit_Heading(self, node: Heading) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Paragraph(self, node: Paragraph) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Bold(self, node: Bold) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Italic(self, node: Italic) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_InternalLink(self, node: InternalLink) -> str:
        return "".join(self.visit(child) for child in node.children) or node.target

    def visit_CategoryLink(self, node: CategoryLink) -> str:
        return node.target

    def visit_ExternalLink(self, node: ExternalLink) -> str:
        return "".join(self.visit(child) for child in node.children) or node.url

    def visit_Image(self, node: Image) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Template(self, node: Template) -> str:
        return node.name

    def visit_TemplateParam(self, node: TemplateParam) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Reference(self, node: Reference) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_List(self, node: ListNode) -> str:
        return "".join(self.visit(item) for item in node.items)

    def visit_ListItem(self, node: ListItem) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Table(self, node: Table) -> str:
        parts: list[str] = []
        for row in node.rows:
            for cell in row.cells:
                parts.append(self.visit(cell))
        return "".join(parts)

    def visit_TableCell(self, node: TableCell) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_CodeBlock(self, node: CodeBlock) -> str:
        return node.content

    def visit_Math(self, node: Math) -> str:
        return node.content

    def visit_HtmlTag(self, node: HtmlTag) -> str:
        return "".join(self.visit(child) for child in node.children)

    def visit_Nowiki(self, node: Nowiki) -> str:
        return node.content

    def visit_ParseError(self, node: ParseError) -> str:
        return node.raw
