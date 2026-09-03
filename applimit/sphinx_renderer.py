from __future__ import annotations

from functools import lru_cache
from importlib import resources
import re


class SphinxRenderError(RuntimeError):
    """Raised when MyST content cannot be converted to HTML."""


_RST_DIRECTIVE_RE = re.compile(r"(?m)^\s*\.\.\s+[a-zA-Z][\w-]*::")
_RST_ROLE_RE = re.compile(r":[a-zA-Z][\w:-]*:`[^`]+`")


def detect_sphinx_syntax(source: str) -> str:
    """Detect imported Sphinx RST while defaulting ambiguous content to MyST."""
    if _RST_DIRECTIVE_RE.search(source) or _RST_ROLE_RE.search(source):
        return "rst"
    if re.search(r"(?m)^\S[^\n]*\n(?:={3,}|-{3,})\s*$", source):
        return "rst"
    return "myst"


def _normalize_rst_sphinx_roles(source: str) -> str:
    """Render common Sphinx-only roles gracefully outside a full docs project.

    Cross-project targets cannot be resolved in a standalone wiki page, but their
    labels should still render as formatted text instead of leaking role syntax.
    """
    role_re = re.compile(r":(?P<role>[a-zA-Z][\w:-]*):`(?P<target>[^`]+)`")

    def replace(match: re.Match[str]) -> str:
        role = match.group("role").split(":")[-1]
        target = match.group("target").strip()
        explicit = re.match(r"(.+?)\s*<([^>]+)>$", target)
        label = explicit.group(1).strip() if explicit else target.lstrip("~")
        if not explicit and target.startswith("~"):
            label = label.rsplit(".", 1)[-1]
        if role in {"class", "func", "meth", "mod", "attr", "data", "obj"}:
            return f"``{label}``"
        return label

    return role_re.sub(replace, source)


@lru_cache(maxsize=128)
def render_sphinx_html(source: str, syntax: str = "myst") -> str:
    """Render MyST or reStructuredText to a safe embeddable HTML fragment.

    MyST is Sphinx's Markdown parser. Raw directives and file inclusion are
    disabled because wiki source can be supplied by end users.
    """
    try:
        from docutils.core import publish_parts
        from docutils.writers.html5_polyglot import Writer
        effective_syntax = detect_sphinx_syntax(source) if syntax in {"auto", "myst"} else syntax
        prepared_source = _normalize_rst_sphinx_roles(source) if effective_syntax == "rst" else source
        if effective_syntax == "rst":
            from docutils.parsers.rst import Parser
        else:
            from myst_parser.parsers.docutils_ import Parser

        parts = publish_parts(
            source=prepared_source,
            parser=Parser(),
            writer=Writer(),
            settings_overrides={
                "doctitle_xform": False,
                "initial_header_level": 1,
                "raw_enabled": False,
                "file_insertion_enabled": False,
                "halt_level": 5,
                "report_level": 5,
                "myst_enable_extensions": [
                    "colon_fence",
                    "deflist",
                    "dollarmath",
                    "tasklist",
                ],
            },
        )
        return str(parts.get("fragment") or parts.get("html_body") or "")
    except Exception as exc:
        raise SphinxRenderError(f"Sphinx/MyST rendering failed: {exc}") from exc


def render_myst_html(source: str) -> str:
    """Backward-compatible MyST renderer."""
    return render_sphinx_html(source, "myst")


@lru_cache(maxsize=1)
def renku_theme_css() -> str:
    """Return RTD base + Renku overrides for isolated wiki rendering."""
    candidates = (
        ("sphinx_rtd_theme", "static/css/theme.css"),
        ("renku_sphinx_theme", "static/fonts.css"),
        ("renku_sphinx_theme", "static/custom.css"),
    )
    chunks: list[str] = []
    for package, relative_path in candidates:
        try:
            asset = resources.files(package).joinpath(relative_path)
            chunks.append(asset.read_text(encoding="utf-8"))
        except (FileNotFoundError, ModuleNotFoundError):
            continue
    if not chunks:
        raise SphinxRenderError("Renku theme assets are not installed.")
    try:
        from pygments.formatters import HtmlFormatter

        chunks.append(HtmlFormatter(style="default").get_style_defs(".highlight"))
    except ImportError:
        pass
    chunks.append(
        """
:root { --merlin-main: #0ec8c3; --merlin-border: #e3e3e3; }
* { box-sizing: border-box; }
body { margin: 0; }
.wy-grid-for-nav { min-height: 620px; background: #fcfcfc; }
.wy-nav-side { background: #fff !important; border-right: 1px solid var(--merlin-border); }
.wy-side-scroll { background: #fff !important; }
.wy-side-nav-search { background: #000 !important; padding: 1.25rem 1rem !important; }
.wy-side-nav-search .icon-home { color: #fff !important; font-size: 1.05rem; font-weight: 700; }
.wy-side-nav-search input { border-color: transparent !important; border-radius: 4px !important; box-shadow: none !important; }
.wy-menu-vertical a { color: #2b2d30 !important; background: #fff !important; }
.wy-menu-vertical a:hover, .wy-menu-vertical li.current > a { color: var(--merlin-main) !important; }
.wy-menu-vertical li.current > a { border-left: 3px solid var(--merlin-main); }
.wy-nav-content-wrap { background: #fcfcfc !important; }
.wy-nav-content { max-width: 1200px !important; min-height: 620px; margin: 0 auto; background: #fff; }
.rst-content { color: #202124; font-size: 16px; line-height: 1.65; }
.rst-content a { color: var(--merlin-main) !important; }
.rst-content h1 { font-size: 2.25rem; font-weight: 600; margin-bottom: 1.5rem; }
.rst-content h2 { font-size: 1.75rem; margin-top: 2.2rem; }
.rst-content h3 { font-size: 1.35rem; margin-top: 1.8rem; }
.rst-content .headerlink { opacity: 0; padding-left: .35rem; text-decoration: none; }
.rst-content h1:hover .headerlink, .rst-content h2:hover .headerlink, .rst-content h3:hover .headerlink { opacity: 1; }
.rst-content div.highlight { border-radius: 6px; margin: 1rem 0; overflow: hidden; }
.rst-content div.highlight pre { margin: 0; padding: 1rem 1.15rem; overflow-x: auto; }
.rst-content code.literal { padding: 2px 5px; border-radius: 4px; color: #e74c3c; background: #fff; border: 1px solid #e1e4e5; }
.rst-content table.docutils { width: 100%; }
.wy-breadcrumbs { padding: 0; }
.wy-breadcrumbs li { display: inline-block; }
.wy-breadcrumbs li + li::before { content: "›"; margin: 0 .45rem; color: #9ca3af; }
@media screen and (max-width: 768px) {
  .wy-nav-side { display: none; }
  .wy-nav-content-wrap { margin-left: 0; }
  .wy-nav-content { padding: 1.25rem; }
}
"""
    )
    return "\n".join(chunks)
