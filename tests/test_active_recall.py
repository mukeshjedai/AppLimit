import base64
import hashlib
import hmac
import json
import time
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applimit.active_recall import create_router


def token(email, secret="recall-test-secret", expired=False):
    encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    message = encode({"alg": "HS256"}) + "." + encode({"email": email, "exp": time.time() + (-10 if expired else 3600)})
    signature = base64.urlsafe_b64encode(hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return message + "." + signature


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in ("APPLIMIT_AZURE_STORAGE_CONNECTION_STRING", "AZURE_STORAGE_CONNECTION_STRING", "APPLIMIT_AZURE_STORAGE_ACCOUNT", "AZURE_STORAGE_ACCOUNT", "NEXTAUTH_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTH_SECRET", "recall-test-secret")
    monkeypatch.setenv("APPLIMIT_LOCAL_WIKI_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(create_router(
        lambda *args, **kwargs: ({"title": "Code", "page_type": "html_app"}, "local", None),
        lambda page_id: b'<style>hidden</style><h1>Loop</h1><pre>for x in y:\n    print(x)</pre><script>secret()</script>',
    ))
    with TestClient(app) as value:
        value.cookies.set("applimit_auth", token("alice@example.com"))
        yield value


def create(client):
    response = client.post("/api/active-recall", json={"title": "Training loop", "reference": "zero_grad → forward → loss → backward → step", "prompts": ["Reconstruct the loop", "Why clear gradients?"]})
    assert response.status_code == 200
    return response.json()["session"]["id"]


def test_rounds_persist_and_are_private(client):
    session_id = create(client)
    body = {"responses": ["forward, loss, backward, step", ""], "corrections": "Clear gradients first", "rating": "again"}
    response = client.post(f"/api/active-recall/{session_id}/attempts", json=body)
    assert response.status_code == 200
    attempt = response.json()["attempt"]
    assert (datetime.fromisoformat(attempt["next_review"]) - datetime.fromisoformat(attempt["created_at"])).total_seconds() == 900
    client.post(f"/api/active-recall/{session_id}/attempts", json=body).raise_for_status()
    saved = client.get(f"/api/active-recall/{session_id}").json()
    assert len(saved["attempts"]) == 2
    assert saved["attempts"][0]["responses"] == body["responses"]
    summary = client.get("/api/active-recall").json()["sessions"][0]
    assert summary["attempt_count"] == 2
    assert "reference" not in summary
    client.cookies.set("applimit_auth", token("bob@example.com"))
    assert client.get("/api/active-recall").json()["sessions"] == []
    assert client.get(f"/api/active-recall/{session_id}").status_code == 404
    assert client.post(f"/api/active-recall/{session_id}/attempts", json=body).status_code == 404


@pytest.mark.parametrize("cookie", ["invalid", token("alice@example.com", expired=True), token("alice@example.com", secret="wrong")])
def test_rejects_invalid_auth(client, cookie):
    client.cookies.set("applimit_auth", cookie)
    assert client.get("/api/active-recall").status_code == 401


def test_validation_and_html_reference(client):
    assert client.post("/api/active-recall", json={"title": " ", "reference": "text", "prompts": ["question"]}).status_code == 422
    session_id = create(client)
    for answers in (["", ""], ["only one"]):
        assert client.post(f"/api/active-recall/{session_id}/attempts", json={"responses": answers, "rating": "again"}).status_code == 422
    reference = client.get("/api/active-recall/source/wiki-id").json()["reference"]
    assert "for x in y:\n    print(x)" in reference
    assert "secret()" not in reference and "hidden" not in reference


def test_generate_requires_auth_and_preserves_answer_keys(client, monkeypatch):
    questions = [{"question": "With indices=[6,1,4] and NumPy y=[2,0,1,5,3,4,0], predict y[indices].", "answer": "[0,0,3], selecting y[6], y[1], y[4]."}]
    calls = []
    def generate(reference, count):
        calls.append((reference, count))
        return questions
    monkeypatch.setattr("applimit.active_recall.generate_questions", generate)
    body = {"reference": "Use the same indices to keep each image and its correct label aligned.", "count": 3}
    result = client.post("/api/active-recall/generate", json=body)
    assert result.status_code == 200 and result.json()["questions"] == questions
    assert calls == [(body["reference"], 3)]
    saved = client.post("/api/active-recall", json={"title": "Indexing", "reference": body["reference"], "prompts": [questions[0]["question"]], "answer_keys": [questions[0]["answer"]]}).json()["session"]
    assert client.get(f"/api/active-recall/{saved['id']}").json()["session"]["answer_keys"] == [questions[0]["answer"]]
    assert client.post("/api/active-recall", json={"title": "Mismatch", "reference": "reference", "prompts": ["one", "two"], "answer_keys": ["one"]}).status_code == 422
    client.cookies.clear()
    assert client.post("/api/active-recall/generate", json=body).status_code == 401
    assert len(calls) == 1


def test_generation_failure_and_limits(client, monkeypatch):
    from applimit.recall_generation import GenerationError
    def fail(*args):
        raise GenerationError("AI unavailable")
    monkeypatch.setattr("applimit.active_recall.generate_questions", fail)
    assert client.post("/api/active-recall/generate", json={"reference": "x" * 40, "count": 3}).status_code == 503
    assert client.post("/api/active-recall/generate", json={"reference": "x" * 30001, "count": 3}).status_code == 422
    assert client.post("/api/active-recall/generate", json={"reference": " " * 40, "count": 3}).status_code == 422
