# OpenWiki

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

## AI active recall

In Exams, open Active recall and create a session, or choose **Active recall from this page** on a wiki page. Paste or select a passage, generate questions, review/edit the draft, and start recall. Separate answer keys appear during comparison, not during recall. Manual questions and older sessions remain supported.

Set `OPENAI_API_KEY` on the backend to enable generation. The optional `OPENWIKI_RECALL_MODEL` selects a model supporting Chat Completions structured outputs; otherwise the existing `APPLIMIT_OPENAI_MODEL` setting or `gpt-4.1-mini` is used. Generation accepts 30–30,000 characters and 3–12 requested questions, and may return fewer questions for short passages. Questions and keys are AI-generated drafts for user review.

The visible app name is OpenWiki. Existing deployment names, storage locations, environment variables, and session cookie names are retained for compatibility.
