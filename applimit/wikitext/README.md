# MediaWiki Wikitext Parser

Production-quality parser for Wikipedia / MediaWiki wikitext. Produces a **JSON-serializable AST** — no HTML rendering.

## Architecture

```
wikitext/
├── ast.py         # Strongly typed AST nodes + SourceLocation
├── lexer.py       # SourceReader, location_at(), optional Lexer tokenizer
├── parser.py      # Recursive-descent parser (block + inline)
├── visitor.py     # Visitor pattern + JsonVisitor + PlainTextVisitor
├── extensions.py  # ExtensionRegistry for custom tags
├── renderer.py    # Renderer protocol (delegates to visitors)
└── __init__.py    # Public API
```

### Pipeline

```
Raw wikitext → WikitextParser → Document AST → JsonVisitor → JSON
```

Every AST node includes:

| Field | Description |
|-------|-------------|
| `type` | Node kind (`Template`, `Heading`, `Image`, …) |
| `children` | Nested nodes |
| `attributes` | Extra metadata (tag attrs, link targets, etc.) |
| `location` | `{line, column, offset}` in source |

## Usage

```python
from applimit.wikitext import parse_wikitext, parse_to_json

wiki = open("article.wikitext").read()
doc = parse_wikitext(wiki)
data = parse_to_json(wiki)  # JSON-ready dict
```

## Supported syntax

- **Templates** — `{{Name}}`, params, nesting
- **Links** — `[[Article]]`, `[[Article|Label]]`, `[[Category:X]]`, `[https://…]`
- **Formatting** — `'''bold'''`, `''italic''`, `'''''both'''''`
- **Headings** — `=` … `======` (levels 1–6)
- **Lists** — `*`, `#`, `;`, `:`, mixed nesting
- **Images** — `[[File:…|thumb|caption]]`
- **Math** — `<math>…</math>`
- **References** — `<ref>…</ref>`, `<ref name="x" />`
- **Comments** — `<!-- … -->`
- **Nowiki** — `<nowiki>…</nowiki>`
- **Magic words** — `__TOC__`, `__NOTOC__`, …
- **Horizontal rules** — `----`
- **Tables** — `{| … |}`
- **HTML** — `div`, `span`, `sup`, `sub`, `blockquote`, `gallery`, `pre`, `syntaxhighlight`

## Extensibility

Register handlers without changing parser core:

```python
from applimit.wikitext import ExtensionRegistry, parse_wikitext
from applimit.wikitext.ast import Text

registry = ExtensionRegistry()
registry.register_inline_tag("mytag", lambda p, tag, attrs: Text(text=attrs.get("id", "")))
doc = parse_wikitext("<mytag id='1'/>", registry=registry)
```

Implement `Visitor` in `visitor.py` for custom output (Flutter widgets, Markdown, etc.).

## Error recovery

Malformed markup yields `ParseError` nodes on `parser.errors` and a best-effort AST.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/test_wikitext_parser.py -v
```

Includes a **Quantum mechanics** Wikipedia fixture (`tests/fixtures/quantum_mechanics.wikitext`) as an acceptance test.
