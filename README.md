# AppLimit

YouTube video translator, insights, flashcards, and wiki — **Next.js frontend** + **Azure Functions** backend.

## Quick start (local)

**Backend** (Azure Functions + FastAPI):

```cmd
scripts\run-local.cmd
```

Runs at `http://localhost:7071`.

**Frontend** (Next.js):

```cmd
cd frontend
copy .env.local.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

See `frontend/README.md` for production deployment and environment variables.

## Deploy backend

```cmd
scripts\deploy.cmd
```

## Project layout

| Path | Role |
|------|------|
| `frontend/` | Next.js UI (App Router) |
| `applimit/` | FastAPI app, wiki storage, pipeline |
| `function_app.py` | Azure Functions ASGI host |
| `scripts/` | Local run and Azure publish helpers |

Legacy Jinja templates in `applimit/templates/` remain available on the backend host for transition.
