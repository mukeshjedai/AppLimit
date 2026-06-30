"""Comprehensive tests for the MediaWiki wikitext parser."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from applimit.wikitext import (
    Document,
    ExtensionRegistry,
    JsonRenderer,
    PlainTextRenderer,
    WikitextParser,
    parse_to_json,
    parse_wikitext,
)
from applimit.wikitext.ast import (
    Bold,
    CategoryLink,
    CodeBlock,
    Comment,
    ExternalLink,
    Heading,
    HorizontalRule,
    HtmlTag,
    Image,
    InternalLink,
    Italic,
    ListNode,
    MagicWord,
    Math,
    Nowiki,
    Paragraph,
    Reference,
    Table,
    Template,
    Text,
)

FIXTURES = Path(__file__).parent / "fixtures"
QUANTUM_MECHANICS = FIXTURES / "quantum_mechanics.wikitext"


def parse(text: str) -> Document:
    return parse_wikitext(text)


def as_json(doc: Document) -> dict:
    return JsonRenderer().render_document(doc)


def text_of(node) -> str:
    if isinstance(node, Text):
        return node.text
    if hasattr(node, "children"):
        return "".join(text_of(c) for c in node.children)
    return ""


class TestBasicStructure:
    def test_user_example(self) -> None:
        wiki = (
            "{{Infobox}}\n"
            "== Overview ==\n"
            "'''Quantum mechanics''' is ..."
        )
        data = as_json(parse(wiki))
        assert data["type"] == "Document"
        assert "location" in data
        assert len(data["children"]) == 3
        assert data["children"][0]["type"] == "Template"
        assert data["children"][0]["name"] == "Infobox"
        assert data["children"][1]["type"] == "Heading"
        assert data["children"][1]["level"] == 2
        assert data["children"][1]["text"] == "Overview"
        bold = data["children"][2]["children"][0]
        assert bold["type"] == "Bold"
        assert bold["text"] == "Quantum mechanics"

    def test_empty_document(self) -> None:
        doc = parse("")
        assert doc.children == []

    def test_plain_paragraph(self) -> None:
        doc = parse("Hello world")
        para = doc.children[0]
        assert isinstance(para, Paragraph)
        assert para.children[0].text == "Hello world"  # type: ignore[union-attr]
        assert para.location is not None

    def test_json_api(self) -> None:
        data = parse_to_json("== Title ==")
        assert data["type"] == "Document"
        assert json.dumps(data)


class TestFormatting:
    def test_bold(self) -> None:
        node = parse("'''bold text'''").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(node, Bold)
        assert text_of(node) == "bold text"

    def test_italic(self) -> None:
        node = parse("''italic text''").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(node, Italic)
        assert text_of(node) == "italic text"

    def test_nested_formatting(self) -> None:
        bold = parse("'''bold ''and italic'' mixed'''").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(bold, Bold)
        assert any(isinstance(c, Italic) for c in bold.children)

    def test_bold_italic_five_apostrophes(self) -> None:
        node = parse("'''''both'''''").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(node, Bold)
        assert isinstance(node.children[0], Italic)


class TestLinks:
    def test_internal_link(self) -> None:
        para = parse("See [[Quantum mechanics]] for details.").children[0]
        link = para.children[1]  # type: ignore[union-attr]
        assert isinstance(link, InternalLink)
        assert link.target == "Quantum mechanics"

    def test_internal_link_with_label(self) -> None:
        link = parse("[[Target|Custom label]]").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(link, InternalLink)
        assert link.target == "Target"
        assert text_of(link) == "Custom label"

    def test_category_link(self) -> None:
        link = parse("[[Category:Physics]]").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(link, CategoryLink)
        assert link.target == "Physics"

    def test_external_link(self) -> None:
        link = parse("[https://example.com Example Site]").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(link, ExternalLink)
        assert link.url == "https://example.com"
        assert text_of(link) == "Example Site"

    def test_external_link_bare_url(self) -> None:
        link = parse("[https://example.com]").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(link, ExternalLink)
        assert link.url == "https://example.com"

    def test_image_link(self) -> None:
        node = parse("[[File:Example.jpg|thumb|220px|Alt caption]]").children[0].children[0]  # type: ignore[union-attr]
        assert isinstance(node, Image)
        assert node.type == "Image"
        assert node.target == "File:Example.jpg"
        assert "thumb" in node.options


class TestTemplates:
    def test_simple_template(self) -> None:
        tpl = parse("{{Citation needed}}").children[0]
        assert isinstance(tpl, Template)
        assert tpl.name == "Citation needed"

    def test_nested_templates(self) -> None:
        tpl = parse("{{outer|{{inner|value}}|tail}}").children[0]
        assert isinstance(tpl, Template)
        assert tpl.name == "outer"
        inner = tpl.params[0].children[0]
        assert isinstance(inner, Template)
        assert inner.name == "inner"

    def test_template_with_named_params(self) -> None:
        tpl = parse("{{Infobox person|name=Alice|birth=2000}}").children[0]
        assert isinstance(tpl, Template)
        assert "name" in [p.name for p in tpl.params]

    def test_list_inside_template(self) -> None:
        tpl = parse("{{Navbox\n* item one\n* item two\n}}").children[0]
        assert isinstance(tpl, Template)
        assert tpl.name == "Navbox"
        param_text = PlainTextRenderer().render(tpl.params[0])
        assert "item one" in param_text


class TestLists:
    def test_unordered_list(self) -> None:
        lst = parse("* one\n* two\n** nested").children[0]
        assert isinstance(lst, ListNode)
        assert lst.ordered is False
        assert len(lst.items) == 3
        assert lst.items[2].depth == 2

    def test_ordered_list(self) -> None:
        lst = parse("# first\n# second").children[0]
        assert isinstance(lst, ListNode)
        assert lst.ordered is True

    def test_mixed_nested_lists(self) -> None:
        lst = parse("# one\n#* two\n#** three").children[0]
        assert isinstance(lst, ListNode)
        assert len(lst.items) == 3

    def test_definition_list(self) -> None:
        lst = parse("; term\n: definition").children[0]
        assert isinstance(lst, ListNode)
        assert lst.items[0].term is True


class TestTables:
    def test_basic_table(self) -> None:
        wiki = (
            '{| class="wikitable"\n'
            "|-\n"
            "! Header !! Value\n"
            "|-\n"
            "| cell1 || cell2\n"
            "|}"
        )
        table = parse(wiki).children[0]
        assert isinstance(table, Table)
        assert table.attributes.get("class") == "wikitable"
        assert table.rows[0].cells[0].header is True


class TestReferences:
    def test_ref_with_content(self) -> None:
        ref = parse('Text<ref name="note1">Citation body</ref> more').children[0].children[1]  # type: ignore[union-attr]
        assert isinstance(ref, Reference)
        assert ref.name == "note1"

    def test_self_closing_ref(self) -> None:
        ref = parse('<ref name="reuse" />').children[0]
        assert isinstance(ref, Reference)
        assert ref.self_closing is True


class TestCodeAndMath:
    def test_syntaxhighlight(self) -> None:
        block = parse('<syntaxhighlight lang="python">\nprint("hi")\n</syntaxhighlight>').children[0]
        assert isinstance(block, CodeBlock)
        assert block.language == "python"

    def test_pre_block(self) -> None:
        block = parse("<pre>plain code</pre>").children[0]
        assert isinstance(block, CodeBlock)
        assert block.content == "plain code"

    def test_math_inline(self) -> None:
        math_node = parse("Equation <math>E=mc^2</math> here").children[0].children[1]  # type: ignore[union-attr]
        assert isinstance(math_node, Math)
        assert math_node.content == "E=mc^2"


class TestHeadings:
    @pytest.mark.parametrize(
        "wiki,level",
        [
            ("= Level 1 =", 1),
            ("== Level 2 ==", 2),
            ("=== Level 3 ===", 3),
            ("====== Level 6 ======", 6),
        ],
    )
    def test_heading_levels(self, wiki: str, level: int) -> None:
        heading = parse(wiki).children[0]
        assert isinstance(heading, Heading)
        assert heading.level == level


class TestHtmlAndExtensions:
    def test_inline_span(self) -> None:
        span = parse('Text <span style="color:red">red</span> end').children[0].children[1]  # type: ignore[union-attr]
        assert isinstance(span, HtmlTag)
        assert span.tag == "span"

    def test_void_br_tag(self) -> None:
        br = parse("Line1<br />Line2").children[0].children[1]  # type: ignore[union-attr]
        assert isinstance(br, HtmlTag)
        assert br.void is True

    def test_sup_sub_tags(self) -> None:
        sup = parse("x<sup>2</sup>").children[0].children[1]  # type: ignore[union-attr]
        sub = parse("x<sub>2</sub>").children[0].children[1]  # type: ignore[union-attr]
        assert sup.tag == "sup"
        assert sub.tag == "sub"

    def test_blockquote(self) -> None:
        node = parse("<blockquote>quote</blockquote>").children[0]
        assert isinstance(node, HtmlTag)
        assert node.tag == "blockquote"

    def test_html_comment(self) -> None:
        node = parse("before<!-- hidden -->after").children[0].children[1]  # type: ignore[union-attr]
        assert isinstance(node, Comment)
        assert node.content == " hidden "

    def test_nowiki(self) -> None:
        node = parse("a<nowiki>[[not a link]]</nowiki>b").children[0].children[1]  # type: ignore[union-attr]
        assert isinstance(node, Nowiki)
        assert node.content == "[[not a link]]"

    def test_horizontal_rule(self) -> None:
        doc = parse("Above\n\n----\n\nBelow")
        assert any(isinstance(c, HorizontalRule) for c in doc.children)

    def test_magic_words(self) -> None:
        para = parse("__TOC__\n__NOTOC__").children[0]
        names = [c.name for c in para.children if isinstance(c, MagicWord)]  # type: ignore[union-attr]
        assert "TOC" in names
        assert "NOTOC" in names

    def test_custom_inline_tag_handler(self) -> None:
        registry = ExtensionRegistry()

        def parse_custom(parser: WikitextParser, tag: str, attrs: dict[str, str]):
            return Text(text=f"CUSTOM:{attrs.get('id', '')}")

        registry.register_inline_tag("custom", parse_custom)
        node = parse_wikitext('<custom id="x"/>', registry).children[0].children[0]  # type: ignore[union-attr]
        assert node.text == "CUSTOM:x"  # type: ignore[union-attr]


class TestErrorRecovery:
    def test_unclosed_template(self) -> None:
        parser = WikitextParser("{{broken template")
        doc = parser.parse()
        assert len(doc.children) == 1
        assert parser.errors

    def test_unclosed_internal_link(self) -> None:
        parser = WikitextParser("[[Article without close")
        doc = parser.parse()
        assert doc.children
        assert parser.errors

    def test_malformed_heading(self) -> None:
        doc = WikitextParser("== Not closed heading").parse()
        assert doc.children


class TestPerformance:
    def test_large_article(self) -> None:
        lines = []
        for i in range(5_000):
            if i % 500 == 0:
                lines.append(f"== Section {i // 500} ==")
            elif i % 17 == 0:
                lines.append(f"* list item {i} with [[Link {i}]] and '''bold'''")
            elif i % 23 == 0:
                lines.append(f"{{{{cite web|title=Source {i}|url=https://example.com/{i}}}}}")
            else:
                lines.append(
                    f"Paragraph {i}: '''Quantum mechanics''' describes [[Nature|nature]]."
                    f"<ref>Ref {i}</ref>"
                )
        start = time.perf_counter()
        doc = parse("\n".join(lines))
        elapsed = time.perf_counter() - start
        assert isinstance(doc, Document)
        assert len(doc.children) > 0
        assert elapsed < 60.0


class TestQuantumMechanicsArticle:
    @pytest.fixture(scope="class")
    def quantum_doc(self) -> Document:
        if not QUANTUM_MECHANICS.is_file():
            pytest.skip("Quantum mechanics fixture missing")
        text = QUANTUM_MECHANICS.read_text(encoding="utf-8")
        return parse_wikitext(text)

    def test_parses_without_crashing(self, quantum_doc: Document) -> None:
        assert isinstance(quantum_doc, Document)
        assert len(quantum_doc.children) > 50

    def test_parses_under_time_limit(self) -> None:
        text = QUANTUM_MECHANICS.read_text(encoding="utf-8")
        start = time.perf_counter()
        parse_wikitext(text)
        assert time.perf_counter() - start < 5.0

    def test_recognizes_core_node_types(self, quantum_doc: Document) -> None:
        found: set[str] = set()

        def walk(node) -> None:
            found.add(node.type)
            for child in getattr(node, "children", []):
                walk(child)
            for item in getattr(node, "items", []):
                walk(item)
            for row in getattr(node, "rows", []):
                walk(row)
            for param in getattr(node, "params", []):
                walk(param)

        walk(quantum_doc)
        required = {
            "Template",
            "Heading",
            "Paragraph",
            "InternalLink",
            "Reference",
            "Math",
            "List",
            "Bold",
            "Italic",
        }
        missing = required - found
        assert not missing, f"Missing node types: {missing}"

    def test_has_top_level_templates_and_headings(self, quantum_doc: Document) -> None:
        top_types = [c.type for c in quantum_doc.children[:30]]
        assert "Template" in top_types
        assert "Heading" in top_types

    def test_json_output_shape(self, quantum_doc: Document) -> None:
        data = as_json(quantum_doc)
        assert data["type"] == "Document"
        assert "children" in data
        assert "attributes" in data
        child = data["children"][0]
        assert "type" in child
        assert "children" in child
        assert "attributes" in child

    def test_quantum_mechanics_text_present(self, quantum_doc: Document) -> None:
        plain = PlainTextRenderer().render_document(quantum_doc)
        assert "quantum" in plain.lower()
