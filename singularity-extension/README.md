# Singularity (Chrome / Edge)

ChatGPT in the **side panel**, with workflows that save answers to **AppLimit wiki pages**.

## Context menu actions

| Action | When | What it does |
|--------|------|----------------|
| **Send to Singularity** | Text selected | ChatGPT answer via **Copy** → **paste notes** wiki page, backlinked from your selection |
| **List problems** | Text selected | Same flow; prompt asks for a numbered problem list |
| **Send screenshot to Singularity** | Right-click page | Captures tab screenshot and attaches it in ChatGPT |
| **Open Singularity** | Anywhere | Opens the side panel |

## Setup

1. Load unpacked from `singularity-extension` in `chrome://extensions`.
2. Right-click extension → **Options** (or ⚙ in the panel).
3. Set **AppLimit URL** to your frontend, e.g. `http://localhost:3000`.
4. Run AppLimit backend (`scripts/run-local.cmd`) and frontend (`npm run dev` in `frontend/`).
5. Log in to ChatGPT once inside the side panel.

## Flow (selection → wiki page)

1. Select text on any page.
2. Right-click → **Send to Singularity** or **List problems**.
3. Singularity opens the panel, submits the prompt, copies the ChatGPT reply, and saves paste-notes with a backlink.
4. **Expansion** (optional, on by default): extracts terms, concepts, and problems → creates an **index page** plus one page per term, one per concept, and one **problem set** page. Every page uses **Terms**, **Concepts**, and **Problem list** sections.
5. Opens the answer page (and optionally the index) if enabled in options.

## Notes

- ChatGPT DOM changes may break prompt/send; reload the panel if stuck.
- Default folder ID in options links new pages into that wiki folder.
- Requires Chrome 114+ (Side Panel + declarativeNetRequest).
