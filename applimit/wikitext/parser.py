"""Recursive-descent parser for MediaWiki wikitext."""

from __future__ import annotations

import re

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
    SourceLocation,
    Table,
    TableCell,
    TableRow,
    Template,
    TemplateParam,
    Text,
)
from applimit.wikitext.extensions import (
    ExtensionRegistry,
    default_registry,
    extract_tag_name,
    parse_html_attributes,
)
from applimit.wikitext.lexer import SourceReader, location_at, normalize_wikitext

_HEADING_RE = re.compile(r"^(=+)(.*?)\1\s*$")
_LIST_MARKER_RE = re.compile(r"^([\*#;:]+)\s*")
_TABLE_ATTRS = re.compile(r"^\{\|\s*(.*)$")
_MAGIC_WORDS = frozenset(
    {
        "TOC",
        "NOTOC",
        "FORCETOC",
        "NOGALLERY",
        "NOEDITSECTION",
        "NEWSECTIONLINK",
        "NONEWSECTIONLINK",
    }
)


class WikitextParser:
    """Parse wikitext into a structured AST with error recovery."""

    def __init__(
        self,
        text: str,
        registry: ExtensionRegistry | None = None,
        *,
        source_text: str | None = None,
        offset_base: int = 0,
    ) -> None:
        self.source_text = source_text or normalize_wikitext(text)
        self.offset_base = offset_base
        self.reader = SourceReader(
            normalize_wikitext(text) if source_text is not None else self.source_text
        )
        self.registry = registry or default_registry()
        self.errors: list[ParseError] = []

    def parse(self) -> Document:
        start = self.reader.pos
        children: list[ASTNode] = []
        while not self.reader.at_end():
            self._skip_blank_lines()
            if self.reader.at_end():
                break
            node = self._parse_block()
            if node is not None:
                children.append(node)
        return Document(children=children, location=self._location(start))

    def add_error(self, message: str, raw: str = "", pos: int | None = None) -> ParseError:
        node = ParseError(message=message, raw=raw, location=self._location(pos))
        self.errors.append(node)
        return node

    def parse_template(self) -> ASTNode:
        return self._parse_template()

    def parse_inline_content(
        self,
        stop_at: set[str] | None = None,
        stop_on_newline: bool = False,
    ) -> list[ASTNode]:
        return self._parse_inline(stop_at=stop_at, stop_on_newline=stop_on_newline)

    def _location(self, pos: int | None = None) -> SourceLocation:
        local_pos = self.reader.pos if pos is None else pos
        return location_at(self.source_text, self.offset_base + local_pos)

    def _with_reader(self, text: str, base: int) -> tuple[SourceReader, int]:
        saved = (self.reader, self.offset_base)
        self.offset_base = base
        self.reader = SourceReader(text)
        return saved

    def _restore_reader(self, saved: tuple[SourceReader, int]) -> None:
        self.reader, self.offset_base = saved

    def _parse_block(self) -> ASTNode | None:
        if self._line_is_horizontal_rule():
            start = self.reader.pos
            self._consume_line()
            return HorizontalRule(location=self._location(start))
        if self._starts_with("{|"):
            return self._parse_table()
        if self._starts_with("{{"):
            return self._parse_template()
        if self._starts_with("<!--"):
            return self._parse_comment()
        if self._starts_with("<"):
            block = self._parse_html_block()
            if block is not None:
                return block
        if self._line_starts_with_list_marker():
            return self._parse_list_block()
        if self._line_starts_with_heading():
            return self._parse_heading()
        return self._parse_paragraph()

    def _parse_paragraph(self) -> Paragraph | None:
        start = self.reader.pos
        lines: list[str] = []
        while not self.reader.at_end():
            if self._is_blank_line():
                if lines:
                    break
                self._consume_blank_lines()
                continue
            if lines and self._starts_block_line():
                break
            line_start, line_end = self.reader.current_line()
            if line_start >= line_end:
                break
            lines.append(self.reader.slice(line_start, line_end))
            self.reader.pos = line_end
            if self.reader.peek() == "\n":
                self.reader.advance()
        if not lines:
            return None
        content = "\n".join(lines)
        children = self._parse_inline_from_string(content, offset=start)
        return Paragraph(children=children, location=self._location(start))

    def _parse_heading(self) -> Heading:
        start = self.reader.pos
        line = self._consume_line()
        match = _HEADING_RE.match(line.strip())
        if not match:
            self.add_error("Malformed heading; treating as paragraph", line, pos=start)
            return Heading(
                level=2,
                children=self._parse_inline_from_string(line, offset=start),
                location=self._location(start),
            )
        level = min(len(match.group(1)), 6)
        title = match.group(2).strip()
        return Heading(
            level=level,
            children=self._parse_inline_from_string(title, offset=start),
            location=self._location(start),
        )

    def _parse_list_block(self) -> ListNode:
        start = self.reader.pos
        items: list[ListItem] = []
        ordered: bool | None = None

        while self._line_starts_with_list_marker():
            line_start = self.reader.pos
            line = self._consume_line()
            marker_match = _LIST_MARKER_RE.match(line)
            if not marker_match:
                break
            marker = marker_match.group(1)
            rest = line[marker_match.end() :].strip()

            if marker.startswith("#"):
                is_ordered = True
                depth = len(marker)
                marker_char = "#"
            elif marker.startswith("*"):
                is_ordered = False
                depth = len(marker)
                marker_char = "*"
            elif marker.startswith(";"):
                is_ordered = False
                depth = len(marker)
                marker_char = ";"
                item = ListItem(
                    depth=depth,
                    term=True,
                    marker=marker_char,
                    children=self._parse_inline_from_string(rest, offset=line_start),
                    location=self._location(line_start),
                )
                items.append(item)
                continue
            elif marker.startswith(":"):
                is_ordered = False
                depth = len(marker)
                marker_char = ":"
            else:
                is_ordered = False
                depth = 1
                marker_char = marker[0]

            if ordered is None:
                ordered = is_ordered
            items.append(
                ListItem(
                    depth=depth,
                    marker=marker_char,
                    children=self._parse_inline_from_string(rest, offset=line_start),
                    location=self._location(line_start),
                )
            )

        return ListNode(ordered=bool(ordered), items=items, location=self._location(start))

    def _parse_table(self) -> Table:
        start = self.reader.pos
        first_line = self._consume_line()
        attr_match = _TABLE_ATTRS.match(first_line.strip())
        attributes: dict[str, str] = {}
        if attr_match and attr_match.group(1).strip():
            attributes = parse_html_attributes(f"<table {attr_match.group(1).strip()}>")

        rows: list[TableRow] = []
        current_row: TableRow | None = None

        while not self.reader.at_end():
            self._skip_blank_lines()
            if self._starts_with("|}"):
                self._consume_line()
                break
            if self._starts_with("|-") or self._starts_with("|+"):
                self._consume_line()
                current_row = TableRow(location=self._location(self.reader.pos))
                rows.append(current_row)
                if self._starts_with("!") or self._starts_with("|"):
                    current_row.cells.extend(self._parse_table_row_line())
                continue
            if self._starts_with("!"):
                current_row = TableRow(location=self._location(self.reader.pos))
                rows.append(current_row)
                current_row.cells.extend(self._parse_table_row_line())
                continue
            if self._starts_with("|"):
                line = self._consume_line()
                if current_row is None:
                    current_row = TableRow(location=self._location(self.reader.pos))
                    rows.append(current_row)
                current_row.cells.extend(self._parse_table_cells_from_line(line))
                continue
            if self._starts_block_line(exclude_table=True):
                break
            self._consume_line()

        return Table(rows=rows, attributes=attributes, location=self._location(start))

    def _parse_table_row_line(self) -> list[TableCell]:
        line = self._consume_line()
        return self._parse_table_cells_from_line(line)

    def _parse_table_cells_from_line(self, line: str) -> list[TableCell]:
        cells: list[TableCell] = []
        stripped = line.lstrip()
        header = stripped.startswith("!")
        content = stripped.lstrip("!|")
        for part in self._split_table_cells(content):
            attrs, body = self._split_cell_attrs(part)
            cell_attrs = dict(attrs)
            cells.append(
                TableCell(
                    header=header,
                    attributes=cell_attrs,
                    children=self._parse_inline_from_string(body.strip()),
                )
            )
        return cells

    def _split_table_cells(self, content: str) -> list[str]:
        parts: list[str] = []
        current: list[str] = []
        i = 0
        while i < len(content):
            if content[i : i + 2] == "||":
                parts.append("".join(current))
                current = []
                i += 2
                continue
            if content[i] == "|" and not current:
                i += 1
                continue
            current.append(content[i])
            i += 1
        parts.append("".join(current))
        return parts

    def _split_cell_attrs(self, part: str) -> tuple[dict[str, str], str]:
        if not part.startswith(" "):
            return {}, part
        match = re.match(r"^(\s[\w\s=]+?\s)(.+)$", part, re.DOTALL)
        if not match:
            return {}, part
        attrs = parse_html_attributes(f"<cell {match.group(1).strip()}>")
        return attrs, match.group(2)

    def _parse_template(self) -> Template:
        start = self.reader.pos
        self.reader.advance(2)
        name, params = self._read_template_body()
        if not self._consume("}}"):
            self.add_error("Unclosed template", "{{" + name, pos=start)
        children = self._parse_inline_from_string(name.strip(), offset=start + 2)
        template_name = self._template_name_from_children(children) or name.strip() or "Template"
        return Template(
            name=template_name,
            params=params,
            children=children,
            location=self._location(start),
        )

    def _read_template_body(self) -> tuple[str, list[TemplateParam]]:
        depth = 1
        start = self.reader.pos
        parts: list[str] = []
        params: list[TemplateParam] = []
        param_buffer: list[str] = []
        param_start = start
        in_name = True
        current_param_name: str | None = None

        while not self.reader.at_end() and depth > 0:
            if self._starts_with("{{"):
                depth += 1
                param_buffer.append("{{")
                self.reader.advance(2)
                continue
            if self._starts_with("}}"):
                depth -= 1
                if depth == 0:
                    break
                param_buffer.append("}}")
                self.reader.advance(2)
                continue

            ch = self.reader.peek()
            if ch == "\n" and depth == 1 and in_name and self.reader.pos > start:
                name = self.reader.slice(start, self.reader.pos).strip()
                self.reader.advance()
                in_name = False
                param_buffer = []
                param_start = self.reader.pos
                parts = [name]
                continue

            if ch == "|" and depth == 1 and in_name:
                name = self.reader.slice(start, self.reader.pos)
                self.reader.advance()
                in_name = False
                param_buffer = []
                param_start = self.reader.pos
                current_param_name = None
                parts.append(name)
                continue

            if ch == "|" and depth == 1 and not in_name:
                self._flush_template_param(param_buffer, current_param_name, params, param_start)
                param_buffer = []
                param_start = self.reader.pos + 1
                current_param_name = None
                self.reader.advance()
                continue

            if (
                ch == "="
                and depth == 1
                and not in_name
                and current_param_name is None
                and param_buffer
            ):
                current_param_name = "".join(param_buffer).strip()
                param_buffer = []
                self.reader.advance()
                continue

            if not (depth == 1 and in_name):
                param_buffer.append(ch)
            self.reader.advance()

        if in_name:
            name = self.reader.slice(start, self.reader.pos)
        else:
            name = parts[0] if parts else self.reader.slice(start, self.reader.pos)
            self._flush_template_param(param_buffer, current_param_name, params, param_start)

        return name.strip(), params

    def _flush_template_param(
        self,
        buffer: list[str],
        name: str | None,
        params: list[TemplateParam],
        param_start: int,
    ) -> None:
        if not buffer and name is None:
            return
        content = "".join(buffer)
        params.append(
            TemplateParam(
                name=name,
                children=self._parse_inline_from_string(content, offset=param_start),
                location=self._location(param_start),
            )
        )

    def _parse_html_block(self) -> ASTNode | None:
        line_start = self.reader.pos
        end = self.reader.text.find(">", self.reader.pos)
        if end == -1:
            return None
        open_tag = self.reader.slice(self.reader.pos, end + 1)
        tag = extract_tag_name(open_tag)
        attrs = parse_html_attributes(open_tag)

        custom = self.registry.block_tags.get(tag)
        if custom is not None:
            self.reader.pos = end + 1
            result = custom(self, tag)
            if result is not None:
                return result

        if tag == "syntaxhighlight":
            return self._parse_code_block(open_tag, attrs, "syntaxhighlight", line_start)
        if tag == "pre":
            return self._parse_code_block(open_tag, attrs, "pre", line_start)
        if tag == "math":
            return self._parse_math_block(open_tag, attrs, line_start)
        if tag == "ref":
            return self._parse_ref_block(open_tag, attrs, line_start)
        if tag == "nowiki":
            return self._parse_nowiki_block(open_tag, line_start)
        if tag == "gallery":
            return self._parse_gallery_block(open_tag, attrs, line_start)

        if self.registry.is_block_html(tag):
            return self._parse_generic_html_block(open_tag, tag, attrs, line_start)

        self.reader.pos = line_start
        return None

    def _parse_code_block(
        self,
        open_tag: str,
        attrs: dict[str, str],
        tag_name: str,
        start: int,
    ) -> CodeBlock:
        self.reader.advance(len(open_tag))
        end_tag = f"</{tag_name}>"
        content_start = self.reader.pos
        close = self.reader.text.lower().find(end_tag.lower(), content_start)
        if close == -1:
            content = self.reader.text[content_start:]
            self.reader.pos = self.reader.length
            self.add_error(f"Unclosed <{tag_name}> tag", open_tag, pos=start)
        else:
            content = self.reader.text[content_start:close]
            self.reader.pos = close + len(end_tag)
        return CodeBlock(
            content=content,
            language=attrs.get("lang") or attrs.get("language"),
            tag=tag_name,
            attributes=attrs,
            location=self._location(start),
        )

    def _parse_math_block(self, open_tag: str, attrs: dict[str, str], start: int) -> Math:
        self.reader.advance(len(open_tag))
        close = self.reader.text.lower().find("</math>", self.reader.pos)
        if close == -1:
            content = self.reader.text[self.reader.pos :]
            self.reader.pos = self.reader.length
            self.add_error("Unclosed <math> tag", open_tag, pos=start)
        else:
            content = self.reader.text[self.reader.pos : close]
            self.reader.pos = close + len("</math>")
        return Math(
            content=content,
            display=attrs.get("display", "").lower() in {"block", "true"},
            attributes=attrs,
            location=self._location(start),
        )

    def _parse_ref_block(self, open_tag: str, attrs: dict[str, str], start: int) -> Reference:
        if open_tag.rstrip().endswith("/>"):
            self.reader.advance(len(open_tag))
            return Reference(
                name=attrs.get("name"),
                self_closing=True,
                attributes=attrs,
                location=self._location(start),
            )
        self.reader.advance(len(open_tag))
        close = self.reader.text.lower().find("</ref>", self.reader.pos)
        if close == -1:
            content = self.reader.text[self.reader.pos :]
            self.reader.pos = self.reader.length
            self.add_error("Unclosed <ref> tag", open_tag, pos=start)
            children = [Text(text=content, location=self._location(self.reader.pos))]
        else:
            content = self.reader.text[self.reader.pos : close]
            self.reader.pos = close + len("</ref>")
            children = self._parse_inline_from_string(content, offset=self.reader.pos - len(content))
        return Reference(
            name=attrs.get("name"),
            children=children,
            attributes=attrs,
            location=self._location(start),
        )

    def _parse_nowiki_block(self, open_tag: str, start: int) -> Nowiki:
        self.reader.advance(len(open_tag))
        close = self.reader.text.lower().find("</nowiki>", self.reader.pos)
        if close == -1:
            content = self.reader.text[self.reader.pos :]
            self.reader.pos = self.reader.length
            self.add_error("Unclosed <nowiki> tag", open_tag, pos=start)
        else:
            content = self.reader.text[self.reader.pos : close]
            self.reader.pos = close + len("</nowiki>")
        return Nowiki(content=content, location=self._location(start))

    def _parse_gallery_block(self, open_tag: str, attrs: dict[str, str], start: int) -> HtmlTag:
        self.reader.advance(len(open_tag))
        close = self._find_closing_tag("gallery", self.reader.pos)
        if close == -1:
            inner = self.reader.text[self.reader.pos :]
            self.reader.pos = self.reader.length
            self.add_error("Unclosed <gallery> tag", open_tag, pos=start)
            children: list[ASTNode] = []
        else:
            inner = self.reader.text[self.reader.pos : close]
            self.reader.pos = close + len("</gallery>")
            children = self._parse_blocks_from_string(inner, offset=self.reader.pos - len(inner))
        return HtmlTag(tag="gallery", attributes=attrs, children=children, location=self._location(start))

    def _parse_generic_html_block(
        self,
        open_tag: str,
        tag: str,
        attrs: dict[str, str],
        start: int,
    ) -> HtmlTag:
        self.reader.advance(len(open_tag))
        close_tag = f"</{tag}>"
        content_start = self.reader.pos
        close = self._find_closing_tag(tag, content_start)
        if close == -1:
            inner = self.reader.text[content_start:]
            self.reader.pos = self.reader.length
            self.add_error(f"Unclosed <{tag}> block", open_tag, pos=start)
            children = self._parse_blocks_from_string(inner, offset=content_start)
        else:
            inner = self.reader.text[content_start:close]
            self.reader.pos = close + len(close_tag)
            children = self._parse_blocks_from_string(inner, offset=content_start)
        return HtmlTag(tag=tag, attributes=attrs, children=children, location=self._location(start))

    def _parse_comment(self) -> Comment:
        start = self.reader.pos
        end = self.reader.text.find("-->", self.reader.pos + 4)
        if end == -1:
            content = self.reader.text[self.reader.pos :]
            self.reader.pos = self.reader.length
            self.add_error("Unclosed HTML comment", "<!--", pos=start)
        else:
            content = self.reader.slice(self.reader.pos + 4, end)
            self.reader.pos = end + 3
        return Comment(content=content, location=self._location(start))

    def _parse_nowiki_inline(self, open_tag: str, start: int) -> Nowiki:
        self.reader.advance(len(open_tag))
        close = self.reader.text.lower().find("</nowiki>", self.reader.pos)
        if close == -1:
            content = self.reader.text[self.reader.pos :]
            self.reader.pos = self.reader.length
            self.add_error("Unclosed <nowiki> tag", open_tag, pos=start)
        else:
            content = self.reader.text[self.reader.pos : close]
            self.reader.pos = close + len("</nowiki>")
        return Nowiki(content=content, location=self._location(start))

    def _parse_magic_word(self, start: int) -> MagicWord | None:
        end = self.reader.text.find("__", self.reader.pos + 2)
        if end == -1:
            return None
        name = self.reader.slice(self.reader.pos + 2, end)
        if name not in _MAGIC_WORDS:
            return None
        self.reader.pos = end + 2
        return MagicWord(name=name, location=self._location(start))

    def _parse_inline(self, stop_at: set[str] | None = None, stop_on_newline: bool = False) -> list[ASTNode]:
        nodes: list[ASTNode] = []
        stop_at = stop_at or set()

        while not self.reader.at_end():
            if stop_on_newline and self.reader.peek() == "\n":
                break
            if self._match_any(stop_at):
                break

            if self._starts_with("__"):
                start = self.reader.pos
                magic = self._parse_magic_word(start)
                if magic is not None:
                    nodes.append(magic)
                    continue
            if self._starts_with("<!--"):
                nodes.append(self._parse_comment())
                continue
            if self._starts_with("'''") or self._starts_with("''"):
                nodes.append(self._parse_apostrophes())
                continue
            if self._starts_with("[["):
                nodes.append(self._parse_internal_link())
                continue
            if self._starts_with("["):
                nodes.append(self._parse_external_link())
                continue
            if self._starts_with("{{"):
                nodes.append(self._parse_template())
                continue
            if self._starts_with("<"):
                inline = self._parse_html_inline()
                if inline is not None:
                    nodes.append(inline)
                    continue

            nodes.append(self._parse_text_run(stop_at, stop_on_newline))

        return self._merge_text_nodes(nodes)

    def _parse_apostrophes(self) -> ASTNode:
        start = self.reader.pos
        count = 0
        while self.reader.peek() == "'":
            count += 1
            self.reader.advance()
        if count >= 6:
            count = 5
        if count == 5:
            inner = self._parse_inline_until_apostrophe(5)
            return Bold(children=[Italic(children=inner)], location=self._location(start))
        if count == 3:
            return Bold(
                children=self._parse_inline_until_apostrophe(3),
                location=self._location(start),
            )
        if count == 2:
            return Italic(
                children=self._parse_inline_until_apostrophe(2),
                location=self._location(start),
            )
        return Text(text="'" * count, location=self._location(start))

    def _parse_inline_until_apostrophe(self, needed: int) -> list[ASTNode]:
        content: list[ASTNode] = []
        while not self.reader.at_end():
            if self.reader.peek() == "'" and self._count_apostrophes() >= needed:
                self.reader.advance(needed)
                return content
            if self._starts_with("__"):
                start = self.reader.pos
                magic = self._parse_magic_word(start)
                if magic is not None:
                    content.append(magic)
                    continue
            if self._starts_with("<!--"):
                content.append(self._parse_comment())
                continue
            if self._starts_with("'''") or self._starts_with("''"):
                content.append(self._parse_apostrophes())
                continue
            if self._starts_with("[["):
                content.append(self._parse_internal_link())
                continue
            if self._starts_with("{{"):
                content.append(self._parse_template())
                continue
            if self._starts_with("<"):
                node = self._parse_html_inline()
                if node is not None:
                    content.append(node)
                    continue
            content.append(self._parse_text_run(set(), False))
        self.add_error(f"Unclosed apostrophe formatting ({needed})", "")
        return content

    def _count_apostrophes(self) -> int:
        count = 0
        offset = 0
        while self.reader.peek(offset) == "'":
            count += 1
            offset += 1
        return count

    def _parse_internal_link(self) -> ASTNode:
        start = self.reader.pos
        self.reader.advance(2)
        content_start = self.reader.pos
        close = self._find_wiki_link_close()
        if close == -1:
            self.add_error("Unclosed internal link", "[[", pos=start)
            return Text(text="[[", location=self._location(start))
        raw = self.reader.slice(content_start, close)
        self.reader.pos = close + 2
        parts = [part.strip() for part in raw.split("|")]
        target = parts[0]
        lower = target.lower()
        if lower.startswith("file:") or lower.startswith("image:"):
            options = parts[1:]
            caption = options[-1] if options else ""
            return Image(
                target=target,
                options=options,
                children=self._parse_inline_from_string(caption, offset=content_start),
                location=self._location(start),
            )
        if lower.startswith("category:"):
            label = parts[1] if len(parts) > 1 else target.split(":", 1)[-1]
            return CategoryLink(
                target=target.split(":", 1)[-1],
                children=self._parse_inline_from_string(label, offset=content_start),
                location=self._location(start),
            )
        label = parts[1] if len(parts) > 1 else target
        return InternalLink(
            target=target,
            children=self._parse_inline_from_string(label, offset=content_start),
            location=self._location(start),
        )

    def _parse_external_link(self) -> ExternalLink:
        start = self.reader.pos
        self.reader.advance()
        content_start = self.reader.pos
        close = self.reader.text.find("]", self.reader.pos)
        if close == -1:
            self.add_error("Unclosed external link", "[", pos=start)
            return ExternalLink(url="", children=[Text(text="[", location=self._location(start))], location=self._location(start))
        raw = self.reader.slice(content_start, close)
        self.reader.pos = close + 1
        parts = raw.split(None, 1)
        url = parts[0]
        label = parts[1] if len(parts) > 1 else url
        return ExternalLink(
            url=url,
            children=self._parse_inline_from_string(label, offset=content_start),
            location=self._location(start),
        )

    def _parse_html_inline(self) -> ASTNode | None:
        start = self.reader.pos
        end = self.reader.text.find(">", self.reader.pos)
        if end == -1:
            return Text(text="<", location=self._location(start))
        open_tag = self.reader.slice(self.reader.pos, end + 1)
        tag = extract_tag_name(open_tag)
        attrs = parse_html_attributes(open_tag)

        custom = self.registry.inline_tags.get(tag)
        if custom is not None:
            self.reader.pos = end + 1
            result = custom(self, tag, attrs)
            if result is not None:
                return result

        if tag == "ref":
            return self._parse_ref_block(open_tag, attrs, start)
        if tag == "math":
            return self._parse_math_block(open_tag, attrs, start)
        if tag == "nowiki":
            return self._parse_nowiki_inline(open_tag, start)

        if open_tag.rstrip().endswith("/>") or tag in {"br", "hr"}:
            self.reader.pos = end + 1
            return HtmlTag(tag=tag, attributes=attrs, void=True, location=self._location(start))

        if self.registry.is_inline_html(tag) or tag in {"sup", "sub", "blockquote", "span", "div"}:
            self.reader.advance(len(open_tag))
            close = self._find_closing_tag(tag, self.reader.pos)
            if close == -1:
                self.add_error(f"Unclosed inline <{tag}>", open_tag, pos=start)
                return HtmlTag(tag=tag, attributes=attrs, children=[], location=self._location(start))
            inner = self.reader.text[self.reader.pos : close]
            self.reader.pos = close + len(f"</{tag}>")
            return HtmlTag(
                tag=tag,
                attributes=attrs,
                children=self._parse_inline_from_string(inner, offset=self.reader.pos - len(inner)),
                location=self._location(start),
            )

        return None

    def _parse_text_run(self, stop_at: set[str], stop_on_newline: bool) -> Text:
        start = self.reader.pos
        while not self.reader.at_end():
            if stop_on_newline and self.reader.peek() == "\n":
                break
            if self._match_any(stop_at):
                break
            if self._starts_with("__") and self.reader.text.find("__", self.reader.pos + 2) != -1:
                name = self.reader.slice(self.reader.pos + 2, self.reader.text.find("__", self.reader.pos + 2))
                if name in _MAGIC_WORDS:
                    break
            if self._starts_with("<!--"):
                break
            if self._starts_with("'''") or self._starts_with("''"):
                break
            if self._starts_with("[[") or self._starts_with("[") or self._starts_with("{{"):
                break
            if self._starts_with("<"):
                break
            self.reader.advance()
        if self.reader.pos == start:
            self.reader.advance()
        return Text(text=self.reader.slice(start, self.reader.pos), location=self._location(start))

    def _parse_inline_from_string(self, text: str, offset: int | None = None) -> list[ASTNode]:
        if not text:
            return []
        base = self.offset_base + (offset if offset is not None else self.reader.pos)
        saved = self._with_reader(text, base)
        try:
            return self._parse_inline()
        finally:
            self._restore_reader(saved)

    def _parse_blocks_from_string(self, text: str, offset: int | None = None) -> list[ASTNode]:
        if not text:
            return []
        base = self.offset_base + (offset if offset is not None else self.reader.pos)
        saved = self._with_reader(text, base)
        try:
            children: list[ASTNode] = []
            while not self.reader.at_end():
                self._skip_blank_lines()
                if self.reader.at_end():
                    break
                node = self._parse_block()
                if node is not None:
                    children.append(node)
            return children
        finally:
            self._restore_reader(saved)

    def _inline_from_text(self, text: str) -> list[ASTNode]:
        return self._parse_inline_from_string(text)

    @staticmethod
    def _merge_text_nodes(nodes: list[ASTNode]) -> list[ASTNode]:
        merged: list[ASTNode] = []
        for node in nodes:
            if (
                merged
                and isinstance(node, Text)
                and isinstance(merged[-1], Text)
                and merged[-1].location == node.location
            ):
                merged[-1] = Text(
                    text=merged[-1].text + node.text,
                    location=merged[-1].location,
                )
            elif merged and isinstance(node, Text) and isinstance(merged[-1], Text):
                merged[-1] = Text(
                    text=merged[-1].text + node.text,
                    location=merged[-1].location,
                )
            else:
                merged.append(node)
        return merged

    @staticmethod
    def _template_name_from_children(children: list[ASTNode]) -> str:
        if len(children) == 1 and isinstance(children[0], Text):
            return children[0].text.strip()
        parts: list[str] = []
        for child in children:
            if isinstance(child, Text):
                parts.append(child.text)
        return "".join(parts).strip()

    def _find_wiki_link_close(self) -> int:
        pos = self.reader.pos
        while pos < self.reader.length:
            if self.reader.text.startswith("]]", pos):
                return pos
            if self.reader.text.startswith("[[", pos):
                pos += 2
                continue
            pos += 1
        return -1

    def _find_closing_tag(self, tag: str, start: int) -> int:
        pattern = re.compile(rf"</{re.escape(tag)}\s*>", re.IGNORECASE)
        match = pattern.search(self.reader.text, start)
        return match.start() if match else -1

    def _starts_with(self, prefix: str) -> bool:
        return self.reader.text.startswith(prefix, self.reader.pos)

    def _consume(self, text: str) -> bool:
        if self._starts_with(text):
            self.reader.advance(len(text))
            return True
        return False

    def _consume_line(self) -> str:
        start, end = self.reader.current_line()
        line = self.reader.slice(start, end)
        self.reader.pos = end
        if self.reader.peek() == "\n":
            self.reader.advance()
        return line

    def _is_blank_line(self) -> bool:
        if self.reader.at_end():
            return False
        if self.reader.peek() == "\n":
            return True
        return not self.reader.line_text().strip()

    def _skip_blank_lines(self) -> None:
        while not self.reader.at_end() and self._is_blank_line():
            if self.reader.peek() == "\n":
                self.reader.advance()
            else:
                self._consume_line()

    def _consume_blank_lines(self) -> None:
        self._skip_blank_lines()

    def _line_is_horizontal_rule(self) -> bool:
        line = self.reader.line_text().strip()
        return len(line) >= 4 and set(line) == {"-"}

    def _line_starts_with_heading(self) -> bool:
        stripped = self.reader.line_text().lstrip()
        if not stripped.startswith("="):
            return False
        return bool(_HEADING_RE.match(stripped))

    def _line_starts_with_list_marker(self) -> bool:
        stripped = self.reader.line_text().lstrip()
        return bool(_LIST_MARKER_RE.match(stripped))

    def _starts_block_line(self, exclude_table: bool = False) -> bool:
        stripped = self.reader.line_text().lstrip()
        if not stripped:
            return False
        if self._line_is_horizontal_rule():
            return True
        if stripped.startswith("{|") and not exclude_table:
            return True
        if stripped.startswith("{{"):
            return True
        if stripped.startswith("<!--"):
            return True
        if stripped.startswith("<"):
            return True
        if _HEADING_RE.match(stripped):
            return True
        if _LIST_MARKER_RE.match(stripped):
            return True
        return False

    def _match_any(self, prefixes: set[str]) -> bool:
        return any(self._starts_with(prefix) for prefix in prefixes)


def parse_wikitext(text: str, registry: ExtensionRegistry | None = None) -> Document:
    return WikitextParser(text, registry).parse()


def parse_to_json(text: str, registry: ExtensionRegistry | None = None) -> dict:
    from applimit.wikitext.visitor import JsonVisitor

    document = parse_wikitext(text, registry)
    return JsonVisitor().visit(document)
