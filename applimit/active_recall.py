"""Private active-recall sessions and immutable practice attempts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from applimit.google_auth import get_session_user
from applimit.wiki_store import _blob_service_client


def signed_user(request: Request) -> str:
    """Accept the existing frontend JWT or backend signed session cookie."""
    secret = os.environ.get("NEXTAUTH_SECRET", "").strip() or os.environ.get("AUTH_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "Sign-in must be configured to save active recall.")
    token = request.cookies.get("applimit_auth", "")
    try:
        header, payload, signature = token.split(".")
        decode = lambda value: base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        expected = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        if json.loads(decode(header)).get("alg") != "HS256" or not hmac.compare_digest(expected, decode(signature)):
            raise ValueError("Invalid signature")
        user = json.loads(decode(payload))
        if float(user.get("exp", 0)) <= time.time():
            raise ValueError("Expired session")
    except (ValueError, TypeError, KeyError, AttributeError):
        user = get_session_user(request)
    email = user.get("email") if isinstance(user, dict) else None
    if not isinstance(email, str) or not email.strip():
        raise HTTPException(401, "Sign in to use active recall.")
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


class SessionInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    reference: str = Field(min_length=1, max_length=100000)
    prompts: list[str] = Field(min_length=1, max_length=30)
    source_page_id: str = Field(default="", max_length=100, pattern=r"^[a-zA-Z0-9_-]*$")

    @field_validator("title", "reference")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a title and reference material.")
        return value.strip()

    @field_validator("prompts")
    @classmethod
    def valid_prompts(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 1000 for value in values):
            raise ValueError("Each prompt must contain 1–1000 characters.")
        return [value.strip() for value in values]


class AttemptInput(BaseModel):
    responses: list[str] = Field(min_length=1, max_length=30)
    corrections: str = Field(default="", max_length=20000)
    rating: Literal["again", "partial", "remembered"]

    @field_validator("responses")
    @classmethod
    def valid_responses(cls, values: list[str]) -> list[str]:
        if any(len(value) > 20000 for value in values) or not any(value.strip() for value in values):
            raise ValueError("Write at least one recall answer (maximum 20,000 characters each).")
        return values


class RecallStore:
    """Use a separate private prefix, never the public wiki page collection."""
    def __init__(self, owner: str):
        self.prefix = f"active-recall/{owner}/"
        configured = any(os.environ.get(key) for key in (
            "APPLIMIT_AZURE_STORAGE_CONNECTION_STRING", "AZURE_STORAGE_CONNECTION_STRING",
            "APPLIMIT_AZURE_STORAGE_ACCOUNT", "AZURE_STORAGE_ACCOUNT",
        ))
        self.container = _blob_service_client().get_container_client(os.environ.get("APPLIMIT_AZURE_WIKI_CONTAINER", "applimit-wiki")) if configured else None
        self.local = Path(os.environ.get("APPLIMIT_LOCAL_WIKI_DIR", "wiki-data")) / self.prefix

    def read(self, name: str):
        if self.container:
            from azure.core.exceptions import ResourceNotFoundError
            try:
                raw = self.container.download_blob(self.prefix + name).readall()
            except ResourceNotFoundError:
                return None
        else:
            path = self.local / name
            if not path.is_file():
                return None
            raw = path.read_bytes()
        return json.loads(raw)

    def write(self, name: str, value: dict):
        raw = json.dumps(value, ensure_ascii=False).encode()
        if self.container:
            self.container.upload_blob(self.prefix + name, raw, overwrite=False)
        else:
            path = self.local / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(raw)

    def records(self, prefix: str):
        if self.container:
            names = [blob.name[len(self.prefix):] for blob in self.container.list_blobs(name_starts_with=self.prefix + prefix) if blob.name.endswith(".json")]
        else:
            names = [path.relative_to(self.local).as_posix() for path in (self.local / prefix).glob("*.json")]
        return [value for name in names if (value := self.read(name)) is not None]


class ReferenceText(HTMLParser):
    """Extract readable HTML text while retaining code whitespace."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if not self.skip and tag in {"p", "div", "section", "br", "pre", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        elif not self.skip and tag in {"p", "div", "section", "pre", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def create_router(get_page, get_html_document) -> APIRouter:
    def private_response(response: Response):
        response.headers["Cache-Control"] = "private, no-store"

    router = APIRouter(prefix="/api/active-recall", tags=["active recall"], dependencies=[Depends(private_response)])

    def session(store, session_id):
        if len(session_id) != 32 or any(c not in "0123456789abcdef" for c in session_id):
            raise HTTPException(404, "Recall session not found.")
        value = store.read(f"sessions/{session_id}.json")
        if value is None:
            raise HTTPException(404, "Recall session not found.")
        return value

    @router.get("")
    def list_sessions(owner: str = Depends(signed_user)):
        store = RecallStore(owner)
        sessions = []
        for value in store.records("sessions/"):
            attempts = store.records(f"attempts/{value['id']}/")
            latest = max(attempts, key=lambda a: a["created_at"]) if attempts else None
            sessions.append({"id": value["id"], "title": value["title"], "created_at": value["created_at"], "prompt_count": len(value["prompts"]), "attempt_count": len(attempts), "next_review": latest["next_review"] if latest else None})
        return {"sessions": sorted(sessions, key=lambda s: s["created_at"], reverse=True)}

    @router.get("/source/{page_id}")
    def wiki_source(page_id: str, owner: str = Depends(signed_user)):
        if not page_id or len(page_id) > 100 or any(not (c.isascii() and (c.isalnum() or c in "_-")) for c in page_id):
            raise HTTPException(404, "Wiki page not found.")
        page, _, _ = get_page(page_id, allow_local=True)
        if not page:
            raise HTTPException(404, "Wiki page not found.")
        content = str(page.get("body_raw") or page.get("transcript") or "")
        if page.get("page_type") == "html_app":
            content = get_html_document(page_id).decode("utf-8-sig")
        if page.get("page_type") in {"html", "html_app"}:
            parser = ReferenceText()
            parser.feed(content)
            content = "".join(parser.parts).strip()
        if not content.strip():
            raise HTTPException(422, "This page has no text to recall. Paste a reference passage instead.")
        return {"title": page.get("title") or "Wiki recall", "reference": content[:250000], "truncated": len(content) > 250000}

    @router.post("")
    def create_session(body: SessionInput, owner: str = Depends(signed_user)):
        value = {**body.model_dump(), "id": uuid.uuid4().hex, "created_at": datetime.now(timezone.utc).isoformat()}
        RecallStore(owner).write(f"sessions/{value['id']}.json", value)
        return {"session": value}

    @router.get("/{session_id}")
    def get_session(session_id: str, owner: str = Depends(signed_user)):
        store = RecallStore(owner)
        value = session(store, session_id)
        return {"session": value, "attempts": sorted(store.records(f"attempts/{session_id}/"), key=lambda a: a["created_at"], reverse=True)}

    @router.post("/{session_id}/attempts")
    def save_attempt(session_id: str, body: AttemptInput, owner: str = Depends(signed_user)):
        store = RecallStore(owner)
        value = session(store, session_id)
        if len(body.responses) != len(value["prompts"]):
            raise HTTPException(422, "Provide one response slot per prompt.")
        now = datetime.now(timezone.utc)
        delay = {"again": timedelta(minutes=15), "partial": timedelta(days=1), "remembered": timedelta(days=3)}[body.rating]
        attempt = {**body.model_dump(), "id": uuid.uuid4().hex, "created_at": now.isoformat(), "next_review": (now + delay).isoformat()}
        store.write(f"attempts/{session_id}/{attempt['id']}.json", attempt)
        return {"attempt": attempt}

    return router
