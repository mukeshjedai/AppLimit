# Singularity (Chrome / Edge)

ChatGPT in the **side panel**, with workflows that save answers to **AppLimit wiki pages**.

Wiki pages can start Recall, Memorise, Maths, or Notation sessions. Memorise mode builds a memory map, chunks the material, creates useful cues, and revisits missed items through spaced active recall.

Version 1.15 adds a floating **Ask page** toolbar to every normal webpage. Recall, Memorise, Maths, and Notation use selected text when present; otherwise they use the readable page content. The gear opens Singularity settings.

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

## Media tools

- **Shot** attaches a screenshot to ChatGPT.
- The floating **📷** button inside the ChatGPT conversation captures the active webpage and attaches it to the current chat.
- Normal pages use `captureVisibleTab()`. PDFs and restricted pages use Chrome's tab/window/screen picker and convert one selected video frame into a PNG.
- **Save shot** downloads the visible active tab as a PNG.
- **Record / Stop** records audio playing in the active tab. The recording can be played in the panel or downloaded as WebM/Opus.
- **Permissions** opens a dedicated page where Webpage screenshots, Downloads, and Tab audio access can be granted separately.
- The **📄＋** icon beside the green connection dot creates a wiki page directly from the latest ChatGPT response. The first heading or line becomes the page title.

## Flow (selection → wiki page)

1. Select text on any page.
2. Right-click → **Send to Singularity** or **List problems**.
3. Singularity opens the panel, submits the prompt, copies the ChatGPT reply, and saves paste-notes with a backlink.
4. **Expansion** (optional, on by default): extracts terms, concepts, and problems → creates an **index page** plus one page per term, one per concept, and one **problem set** page. Every page uses **Terms**, **Concepts**, and **Problem list** sections.
5. Opens the answer page (and optionally the index) if enabled in options.

## Notes

- ChatGPT DOM changes may break prompt/send; reload the panel if stuck.
- Default folder ID in options links new pages into that wiki folder.
- Media capture requires Chrome 116+; recordings begin only after the user clicks Record.
