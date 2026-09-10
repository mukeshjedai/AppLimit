import json
from types import SimpleNamespace
import pytest
from applimit.recall_generation import generate_questions, GenerationError


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(GenerationError, match="not configured"):
        generate_questions("Reference", 3)


@pytest.mark.parametrize("raw,finish,refusal,valid", [
    (json.dumps({"questions": [{"question": "Predict y[indices].", "answer": "[0, 0, 3]"}]}), "stop", None, True),
    ('{}', "stop", None, False),
    ('{"questions":[{"question":" ","answer":"answer"}]}', "stop", None, False),
    ('{}', "length", None, False),
    ('{}', "stop", "refused", False),
])
def test_structured_response_validation(monkeypatch, raw, finish, refusal, valid):
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = []
    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=raw, refusal=refusal))])
    monkeypatch.setattr(openai, "OpenAI", FakeClient)
    if valid:
        assert generate_questions("same indices", 3)[0]["answer"] == "[0, 0, 3]"
    else:
        with pytest.raises(GenerationError): generate_questions("same indices", 3)
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert "same indices" in calls[0]["messages"][1]["content"]
