"""Azure Functions entry point — hosts the FastAPI app via the ASGI worker."""

from __future__ import annotations

import azure.functions as func

from applimit.web import app as fastapi_app

app = func.AsgiFunctionApp(
    app=fastapi_app,
    http_auth_level=func.AuthLevel.ANONYMOUS,
)
