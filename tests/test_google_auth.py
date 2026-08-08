from applimit.google_auth import (
    create_oauth_state,
    parse_oauth_state,
    safe_next_path,
)


def test_safe_next_path_rejects_external_urls() -> None:
    assert safe_next_path("/wiki") == "/wiki"
    assert safe_next_path("https://evil.com") == "/"
    assert safe_next_path("//evil.com") == "/"
    assert safe_next_path(None) == "/"


def test_signed_oauth_state_roundtrip() -> None:
    state = create_oauth_state("/wiki")
    ok, next_path = parse_oauth_state(state)
    assert ok is True
    assert next_path == "/wiki"


def test_signed_oauth_state_rejects_tampering() -> None:
    ok, next_path = parse_oauth_state("not-a-valid-state")
    assert ok is False
    assert next_path == "/"
