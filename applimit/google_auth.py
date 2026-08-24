import json
import logging
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

log = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
AUTH_COOKIE_NAME = "applimit_auth"
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30

PUBLIC_PATH_PREFIXES = (
    "/login",
    "/sign-in",
    "/auth/",
    "/api/",
    "/static/",
)
PUBLIC_EXACT_PATHS = {"/favicon.ico"}


def is_auth_enabled() -> bool:
    return bool(
        os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        and os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    )


def auth_secret() -> str:
    secret = (
        os.environ.get("AUTH_SECRET", "").strip()
        or os.environ.get("NEXTAUTH_SECRET", "").strip()
    )
    if not secret:
        secret = "applimit-dev-auth-secret-change-me"
    return secret


def auth_base_url(request: Request) -> str:
    configured = os.environ.get("AUTH_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def google_redirect_uri(request: Request) -> str:
    return f"{auth_base_url(request)}/auth/google/callback"


def auth_cookie_secure() -> bool:
    return os.environ.get("AUTH_COOKIE_SECURE", "").strip() == "1"


def _auth_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(auth_secret(), salt="applimit-auth-session")


def create_auth_token(user: dict[str, Any]) -> str:
    return _auth_serializer().dumps(user)


def parse_auth_token(token: str) -> dict[str, Any] | None:
    try:
        data = _auth_serializer().loads(token, max_age=AUTH_COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if isinstance(data, dict) and data.get("email"):
        return data
    return None


def get_session_user(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if token:
        user = parse_auth_token(token)
        if user:
            return user
    return None


def set_auth_cookie(response: Response, user: dict[str, Any]) -> None:
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=create_auth_token(user),
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        secure=auth_cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        AUTH_COOKIE_NAME,
        path="/",
        secure=auth_cookie_secure(),
        samesite="lax",
    )


def is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Google token exchange failed: {detail}") from e
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Google token exchange failed: {e}") from e


def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise HTTPException(status_code=502, detail=f"Google userinfo failed: {e}") from e


def build_google_auth_url(request: Request, state: str) -> str:
    params = {
        "client_id": os.environ["GOOGLE_CLIENT_ID"].strip(),
        "redirect_uri": google_redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_google_code(request: Request, code: str) -> dict[str, Any]:
    payload = {
        "code": code,
        "client_id": os.environ["GOOGLE_CLIENT_ID"].strip(),
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"].strip(),
        "redirect_uri": google_redirect_uri(request),
        "grant_type": "authorization_code",
    }
    token_data = _post_form(GOOGLE_TOKEN_URL, payload)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Google did not return an access token.")
    profile = _get_json(
        GOOGLE_USERINFO_URL,
        {"Authorization": f"Bearer {access_token}"},
    )
    email = profile.get("email")
    if not email:
        raise HTTPException(status_code=403, detail="Google account has no email address.")
    return {
        "sub": profile.get("sub") or email,
        "email": email,
        "name": profile.get("name") or email,
        "picture": profile.get("picture") or "",
    }


def safe_next_path(raw: str | None) -> str:
    if not raw:
        return "/"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


def _oauth_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(auth_secret(), salt="applimit-google-oauth")


def create_oauth_state(next_path: str) -> str:
    """Signed OAuth state (survives redirect without relying on session cookies)."""
    payload = {
        "n": secrets.token_urlsafe(16),
        "next": safe_next_path(next_path),
    }
    return _oauth_serializer().dumps(payload)


def parse_oauth_state(state: str) -> tuple[bool, str]:
    try:
        data = _oauth_serializer().loads(state, max_age=900)
    except (BadSignature, SignatureExpired):
        return False, "/"
    if not isinstance(data, dict):
        return False, "/"
    return True, safe_next_path(str(data.get("next") or "/"))


async def auth_middleware(request: Request, call_next):
    """Require signed auth cookie on protected pages (avoid BaseHTTPMiddleware + sessions)."""
    if not is_auth_enabled() or is_public_path(request.url.path):
        return await call_next(request)
    if get_session_user(request):
        return await call_next(request)
    next_path = urllib.parse.quote(request.url.path)
    return RedirectResponse(url=f"/login?next={next_path}", status_code=307)
