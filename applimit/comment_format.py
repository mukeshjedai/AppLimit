"""Restricted rich text for comment bodies."""
import bleach
import re


class CommentStyles:
    def sanitize_css(self, style):
        allowed = {
            "color": {"red", "black", "blue", "#b91c1c", "#000000", "#1d4ed8", "rgb(185,28,28)", "rgb(0,0,0)", "rgb(29,78,216)", "rgb(255,0,0)", "rgb(0,0,255)"},
            "font-weight": {"bold", "normal", "700", "400"},
            "font-style": {"italic", "normal"},
            "text-decoration": {"underline", "line-through", "none"},
            "text-decoration-line": {"underline", "line-through", "none"},
        }
        output = []
        for declaration in style.split(";"):
            key, sep, value = declaration.partition(":")
            key, value = key.strip().lower(), re.sub(r"\s+", "", value.lower())
            if sep and value in allowed.get(key, set()):
                output.append(f"{key}:{value};")
        return "".join(output)


def clean_comment(value: str, content_format: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if content_format == "html":
        value = bleach.clean(value, tags=["p", "div", "br", "span", "b", "strong", "i", "em", "u", "s", "ul", "ol", "li", "blockquote", "pre", "code"], attributes={"*": ["style"]}, css_sanitizer=CommentStyles(), strip=True)
        import html
        if not html.unescape(bleach.clean(value, tags=[], strip=True)).strip():
            return ""
    return value
