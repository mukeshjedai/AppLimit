from applimit.google_auth import (
    create_auth_token,
    create_oauth_state,
    parse_auth_token,
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


def test_signed_auth_token_roundtrip() -> None:
    user = {
        "sub": "123",
        "email": "test@example.com",
        "name": "Test User",
        "picture": "",
    }
    token = create_auth_token(user)
    parsed = parse_auth_token(token)
    assert parsed == user


def test_signed_auth_token_rejects_tampering() -> None:
    assert parse_auth_token("not-a-valid-token") is None
