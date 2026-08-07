from applimit.wiki_paste import normalize_manual_body, paste_to_display_markdown


def test_chatgpt_bracket_blocks_become_latex_display_math() -> None:
    raw = """### 3. Electricity Demand Forecasting

[
y_{t-1}, y_{t-2}, y_{t-3}, y_{t-24}
]
"""
    out = paste_to_display_markdown(raw)
    assert "\\[" in out
    assert "\\]" in out
    assert "y_{t-1}, y_{t-2}, y_{t-3}, y_{t-24}" in out
    assert "\n[\n" not in out


def test_lag_features_block() -> None:
    raw = """[
Lag1,\\ Lag2,\\ Lag7
]"""
    out = paste_to_display_markdown(raw)
    assert "\\[" in out
    assert "Lag1,\\ Lag2,\\ Lag7" in out


def test_dollar_display_math_from_chatgpt_dom() -> None:
    raw = "Some text\n\n$$\ny = mx + b\n$$\n\nMore"
    out = paste_to_display_markdown(raw)
    assert "\\[" in out
    assert "y = mx + b" in out
    assert "$$" not in out


def test_existing_latex_delimiters_are_preserved() -> None:
    raw = r"\[x^2\]"
    out = paste_to_display_markdown(raw)
    assert out == r"\[x^2\]"


def test_normalize_manual_body_matches_display_pipeline() -> None:
    raw = "[\na_1\n]"
    assert normalize_manual_body(raw) == paste_to_display_markdown(raw)
