# Azure Functions (FastAPI)

This project includes an Azure Functions **Python v2 programming model** entry point that wraps the existing FastAPI app (`applimit.web:app`).

## Prerequisites

- **Python** 3.10 or later (match your Function App on Azure).
- **Azure Functions Core Tools** v4: [Install](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local).
- An Azure Storage account (for `AzureWebJobsStorage` in production).

## Local run

1. Copy `local.settings.json.example` to `local.settings.json` and set `AzureWebJobsStorage` to a real storage connection string for a full local experience, or keep `UseDevelopmentStorage=true` if you use Azurite.

2. Install dependencies (from the repo root):

   ```bash
   pip install -r requirements.txt
   ```

3. Start the Functions host:

   ```bash
   func start
   ```

   The site is served at the URL shown in the terminal (typically `http://localhost:7071`). With `routePrefix` empty in `host.json`, routes match the FastAPI app (`/`, `/insights`, `/api/...`, etc.).

## Deploy to Azure

1. Create a **Python** Function App (runtime **4.x**, OS **Linux** recommended for native dependencies).

2. Configure **Application settings** (at minimum):

   - `AzureWebJobsStorage` — connection string to your storage account.
   - Any keys your app already expects (e.g. OpenAI, Azure Blob for wiki, etc.).

3. Publish from the repo root (Core Tools):

   ```bash
   func azure functionapp publish <YOUR_FUNCTION_APP_NAME> --python --build remote
   ```

   Remote build (`--build remote`) runs Oryx on Azure so Linux wheels match the Function App. Or use **VS Code** Azure extension / **Azure Developer CLI** (`azd`).

### Application settings used for Linux Consumption

These are set on the Function App in Azure (not only in `local.settings.json`):

| Setting | Purpose |
|--------|---------|
| `AzureWebJobsFeatureFlags` = `EnableWorkerIndexing` | Python v2 programming model (ASGI / `AsgiFunctionApp`). |
| `SCM_DO_BUILD_DURING_DEPLOYMENT` = `1` | Run `pip install` during deploy. |
| `ENABLE_ORYX_BUILD` = `true` | Oryx remote build. |
| `APPLIMIT_LOCAL_WIKI_DIR` = `/tmp/applimit-wiki` | Writable folder for the local wiki store when Azure Blob is not used (default `wiki-data` under the read-only app root fails on Linux Consumption). |
| `APPLIMIT_AZURE_STORAGE_CONNECTION_STRING` | **Recommended** so local dev and Azure use the **same** wiki list: paste the storage account connection string in both Function App settings and `local.settings.json`. Alternatively set `APPLIMIT_AZURE_STORAGE_ACCOUNT` and use `DefaultAzureCredential` (managed identity on Azure, `az login` locally). |
| `APPLIMIT_AZURE_WIKI_CONTAINER` | Blob container name (default `applimit-wiki`). |

### Deployed environment (example)

| Item | Value |
|------|--------|
| Resource group | `rg-applimit-97195` |
| Region | East US |
| Storage account | `applimit97195` |
| Function App | `applimit-func-97195` |
| URL | `https://applimit-func-97195.azurewebsites.net` |

Starlette **1.x** expects `Jinja2Templates.TemplateResponse(request, "template.html", context)` (request first). The older `(name, {"request": request, ...})` order breaks HTML routes when pip resolves Starlette 1.0; `applimit/web.py` uses the current signature.

## Important limitations for this codebase

This app is a **heavy** workload (ffmpeg, yt-dlp, optional Whisper, long-running translation jobs). The default **Consumption** Functions plan has **HTTP timeouts** (order of minutes) and a **read-only filesystem** except `TEMP` on Linux. The default image may **not** include **ffmpeg** on PATH.

For serious use of the full pipeline on Azure, consider:

- **Azure App Service** (custom container with ffmpeg + models), or  
- **Container Apps** / **AKS** with a defined image, or  
- A **Premium / Dedicated** Functions plan with a **custom container** and **long timeout** configuration.

The in-memory job store (`_jobs` in `web.py`) is **not** durable across instances or cold starts; production would need a queue + worker or external job store.

The files here wire **hosting** of the FastAPI surface on Azure Functions; operational tuning for video processing is a separate step.
