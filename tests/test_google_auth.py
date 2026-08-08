from applimit.google_auth import safe_next_path


def test_safe_next_path_rejects_external_urls() -> None:
    assert safe_next_path("/wiki") == "/wiki"
    assert safe_next_path("https://evil.com") == "/"
    assert safe_next_path("//evil.com") == "/"
    assert safe_next_path(None) == "/"
