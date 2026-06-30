from __future__ import annotations

import re


def _convert_bracket_display_math(text: str) -> str:
    """
    Turn standalone [ / ] line pairs into LaTeX display math \\[ ... \\].
    Matches the common ChatGPT-style block:
        [
        \\frac{d}{dx} ...
        ]
    """
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if lines[i].strip() == "[":
            start = i
            i += 1
            chunk: list[str] = []
            while i < n and lines[i].strip() != "]":
                chunk.append(lines[i])
                i += 1
            if i >= n or lines[i].strip() != "]":
                out.append(lines[start])
                i = start + 1
                continue
            i += 1
            inner = "\n".join(chunk).strip()
            out.append("")
            out.append("\\[")
            out.append(inner)
            out.append("\\]")
            out.append("")
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def _looks_inline_latex(inner: str) -> bool:
    s = inner.strip()
    if not s:
        return False
    if "\\" in s:
        return True
    if len(s) == 1 and s.isalpha():
        return True
    if "^" in s or "_" in s:
        return True
    if "=" in s and len(s) >= 3:
        return True
    return False


def _convert_inline_math(text: str) -> str:
    """Wrap ( ... ) in \\( ... \\) when it looks like LaTeX. Skips content inside \\[ ... \\]."""
    blocks: list[str] = []

    def stash_display(m: re.Match) -> str:
        blocks.append(m.group(0))
        return f"__MATH_DISPLAY_{len(blocks) - 1}__"

    t = re.sub(r"\\\[[\s\S]*?\\\]", stash_display, text)

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        if _looks_inline_latex(inner):
            return "\\(" + inner + "\\)"
        return m.group(0)

    t = re.sub(r"\(([^)]*)\)", repl, t)

    for i, b in enumerate(blocks):
        t = t.replace(f"__MATH_DISPLAY_{i}__", b)
    return t


def paste_to_display_markdown(raw: str) -> str:
    """
    Normalize pasted notes (ChatGPT-style) to Markdown + LaTeX for KaTeX/markdown-it-texmath.
    Order: display-math brackets first, then inline parentheses.
    """
    t = raw.replace("\r\n", "\n").replace("\r", "\n")
    t = _convert_bracket_display_math(t)
    t = _convert_inline_math(t)
    return t.strip()
