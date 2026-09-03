from __future__ import annotations

from functools import lru_cache
from importlib import resources


class SphinxRenderError(RuntimeError):
    """Raised when MyST content cannot be converted to HTML."""


@lru_cache(maxsize=128)
def render_sphinx_html(source: str, syntax: str = "myst") -> str:
    """Render MyST or reStructuredText to a safe embeddable HTML fragment.

    MyST is Sphinx's Markdown parser. Raw directives and file inclusion are
    disabled because wiki source can be supplied by end users.
    """
    try:
        from docutils.core import publish_parts
        if syntax == "rst":
            from docutils.parsers.rst import Parser
        else:
            from myst_parser.parsers.docutils_ import Parser

        parts = publish_parts(
            source=source,
            parser=Parser(),
            writer_name="html5",
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
    chunks.append(
        """
.wy-nav-content { max-width: 1200px; margin: 0 auto; background: #fff; }
.rst-content { color: #202124; line-height: 1.65; }
.rst-content h1 { font-weight: 600; margin-bottom: 1.5rem; }
.rst-content h2 { margin-top: 2rem; }
.rst-content div.highlight { border-radius: 6px; margin: 1rem 0; }
.rst-content code.literal { padding: 2px 5px; border-radius: 4px; }
.rst-content table.docutils { width: 100%; }
"""
    )
    return "\n".join(chunks)
