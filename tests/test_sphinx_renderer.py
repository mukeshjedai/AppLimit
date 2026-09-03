from applimit.sphinx_renderer import render_myst_html, render_sphinx_html


def test_render_myst_document_fragment() -> None:
    html = render_myst_html(
        "# Reservoir\n\n**Strong** text with [link](https://example.com).\n\n"
        "```python\nprint('hello')\n```\n"
    )

    assert "Reservoir" in html
    assert "<strong>Strong</strong>" in html
    assert 'href="https://example.com"' in html
    assert "print" in html


def test_raw_html_is_not_executed() -> None:
    html = render_myst_html("# Safe\n\n<script>alert('x')</script>")

    assert "<script>" not in html


def test_render_restructured_text() -> None:
    html = render_sphinx_html(
        "Reservoir\n=========\n\n.. code-block:: python\n\n   print('hello')\n",
        "rst",
    )

    assert "Reservoir" in html
    assert "print" in html
