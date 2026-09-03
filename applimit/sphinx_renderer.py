from __future__ import annotations

from functools import lru_cache


class SphinxRenderError(RuntimeError):
    """Raised when MyST content cannot be converted to HTML."""


@lru_cache(maxsize=128)
def render_myst_html(source: str) -> str:
    """Render a MyST Markdown document to a safe, embeddable HTML fragment.

    MyST is Sphinx's Markdown parser. Raw directives and file inclusion are
    disabled because wiki source can be supplied by end users.
    """
    try:
        from docutils.core import publish_parts
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
