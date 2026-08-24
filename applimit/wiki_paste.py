from __future__ import annotations

import re


def _looks_like_math_content(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    if "\\" in s:
        return True
    if re.search(r"[_^{=]", s):
        return True
    if re.search(r"\b(Lag|lag)_?\d", s):
        return True
    return False


def _convert_dollar_display_math(text: str) -> str:
    """Convert $$ ... $$ (ChatGPT / DOM export) to \\[ ... \\]."""

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        return f"\n\n\\[\n{inner}\n\\]\n\n"

    return re.sub(r"\$\$([\s\S]+?)\$\$", repl, text)


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
        stripped = lines[i].strip()
        if stripped in ("\\[", "["):
            start = i
            i += 1
            chunk: list[str] = []
            close = "\\]" if stripped == "\\[" else "]"
            while i < n and lines[i].strip() != close:
                chunk.append(lines[i])
                i += 1
            if i >= n or lines[i].strip() != close:
                out.append(lines[start])
                i = start + 1
                continue
            i += 1
            inner = "\n".join(chunk).strip()
            if not _looks_like_math_content(inner):
                out.append(lines[start])
                out.extend(chunk)
                if i <= n:
                    out.append("]" if stripped == "[" else "\\]")
                continue
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


def _convert_dollar_inline_math(text: str) -> str:
    """Convert $ ... $ to \\( ... \\) when it looks like LaTeX."""

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        if _looks_inline_latex(inner):
            return "\\(" + inner + "\\)"
        return m.group(0)

    return re.sub(r"(?<!\$)\$(?!\$)([^\$\n]+?)\$(?!\$)", repl, text)


def _convert_inline_math(text: str) -> str:
    """Wrap ( ... ) in \\( ... \\) when it looks like LaTeX. Skips existing \\[ ... \\] / \\( ... \\)."""
    blocks: list[str] = []

    def stash(m: re.Match[str]) -> str:
        blocks.append(m.group(0))
        return f"__MATH_BLOCK_{len(blocks) - 1}__"

    t = re.sub(r"\\\[[\s\S]*?\\\]", stash, text)
    t = re.sub(r"\\\([\s\S]*?\\\)", stash, t)

    def repl(m: re.Match[str]) -> str:
        inner = m.group(1)
        if _looks_inline_latex(inner):
            return "\\(" + inner + "\\)"
        return m.group(0)

    t = re.sub(r"\(([^)]*)\)", repl, t)

    for i, b in enumerate(blocks):
        t = t.replace(f"__MATH_BLOCK_{i}__", b)
    return t


def paste_to_display_markdown(raw: str) -> str:
    """
    Normalize pasted notes (ChatGPT-style) to Markdown + LaTeX for KaTeX/markdown-it-texmath.
    Converts ChatGPT-style [ ... ] blocks, $$ ... $$, and parenthesis/dollar inline math.
    """
    t = raw.replace("\r\n", "\n").replace("\r", "\n")
    t = _convert_dollar_display_math(t)
    t = _convert_bracket_display_math(t)
    t = _convert_dollar_inline_math(t)
    t = _convert_inline_math(t)
    return t.strip()


def normalize_manual_body(raw: str) -> str:
    """Canonical form for storing manual (paste) notes so math delimiters survive round-trips."""
    return paste_to_display_markdown(raw)
