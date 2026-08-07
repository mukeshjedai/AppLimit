/**
 * Shared wiki markdown helpers: video/link embed syntax and markdown-it plugin.
 *
 * Embed syntax (stored in page body):
 *   @[video](https://youtube.com/watch?v=...)
 *   @[link](https://example.com)
 *   @[link](https://example.com "Optional title")
 */

export function parseYouTubeId(url) {
  try {
    const u = new URL(url.trim());
    const host = u.hostname.replace(/^www\./, "");
    if (host === "youtu.be") {
      const id = u.pathname.slice(1).split("/")[0];
      return id || null;
    }
    if (host === "youtube.com" || host === "m.youtube.com" || host === "music.youtube.com") {
      if (u.pathname.startsWith("/embed/")) {
        return u.pathname.split("/")[2] || null;
      }
      if (u.pathname.startsWith("/shorts/")) {
        return u.pathname.split("/")[2] || null;
      }
      return u.searchParams.get("v");
    }
  } catch (_) {}
  return null;
}

export function parseVimeoId(url) {
  try {
    const u = new URL(url.trim());
    const host = u.hostname.replace(/^www\./, "");
    if (host === "vimeo.com") {
      const parts = u.pathname.split("/").filter(Boolean);
      return parts[0] || null;
    }
    if (host === "player.vimeo.com") {
      const m = u.pathname.match(/\/video\/(\d+)/);
      return m ? m[1] : null;
    }
  } catch (_) {}
  return null;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function safeHttpUrl(url) {
  try {
    const u = new URL(String(url).trim());
    if (u.protocol === "http:" || u.protocol === "https:") return u.href;
  } catch (_) {}
  return null;
}

function resolveVideoUrl(url) {
  const trimmed = String(url || "").trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("/") && !trimmed.startsWith("//")) return trimmed;
  return safeHttpUrl(trimmed);
}

export function videoEmbedHtml(url) {
  const safe = resolveVideoUrl(url);
  if (!safe) {
    return `<p class="wiki-embed wiki-embed--error">Invalid video URL.</p>`;
  }

  const absoluteForParse = safe.startsWith("/")
    ? `${window.location.origin}${safe}`
    : safe;

  const yt = parseYouTubeId(absoluteForParse);
  if (yt) {
    const src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(yt)}`;
    return (
      `<div class="wiki-embed wiki-embed-video">` +
      `<iframe src="${escapeHtml(src)}" title="Embedded video" ` +
      `allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" ` +
      `allowfullscreen loading="lazy"></iframe></div>`
    );
  }

  const vimeo = parseVimeoId(absoluteForParse);
  if (vimeo) {
    const src = `https://player.vimeo.com/video/${encodeURIComponent(vimeo)}`;
    return (
      `<div class="wiki-embed wiki-embed-video">` +
      `<iframe src="${escapeHtml(src)}" title="Embedded video" ` +
      `allow="autoplay; fullscreen; picture-in-picture" allowfullscreen loading="lazy"></iframe></div>`
    );
  }

  if (/\.(mp4|webm|ogg|mov|m4v)(\?|#|$)/i.test(safe)) {
    return (
      `<div class="wiki-embed wiki-embed-video">` +
      `<video controls preload="metadata" src="${escapeHtml(safe)}"></video></div>`
    );
  }

  return (
    `<div class="wiki-embed wiki-embed-link">` +
    `<a class="wiki-embed-link__anchor" href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">` +
    `<span class="wiki-embed-link__label">Video link</span>` +
    `<span class="wiki-embed-link__url">${escapeHtml(safe)}</span>` +
    `</a></div>`
  );
}

export function linkEmbedHtml(url, title) {
  const safe = safeHttpUrl(url);
  if (!safe) {
    return `<p class="wiki-embed wiki-embed--error">Invalid URL.</p>`;
  }
  let host = safe;
  try {
    host = new URL(safe).hostname.replace(/^www\./, "");
  } catch (_) {}
  const label = (title || "").trim() || host;
  return (
    `<div class="wiki-embed wiki-embed-link">` +
    `<a class="wiki-embed-link__anchor" href="${escapeHtml(safe)}" target="_blank" rel="noopener noreferrer">` +
    `<span class="wiki-embed-link__label">${escapeHtml(label)}</span>` +
    `<span class="wiki-embed-link__url">${escapeHtml(safe)}</span>` +
    `</a></div>`
  );
}

const EMBED_INLINE_RE = /^@\[(video|link|url)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/;

export function wikiEmbedPlugin(md) {
  function wikiEmbedInline(state, silent) {
    if (state.src.charCodeAt(state.pos) !== 0x40 /* @ */) return false;

    const tail = state.src.slice(state.pos);
    const match = tail.match(EMBED_INLINE_RE);
    if (!match) return false;

    if (!silent) {
      const token = state.push("wiki_embed", "", 0);
      token.content = match[0];
      token.meta = {
        kind: match[1] === "url" ? "link" : match[1],
        url: match[2],
        title: match[3] || "",
      };
    }

    state.pos += match[0].length;
    return true;
  }

  md.inline.ruler.before("link", "wiki_embed", wikiEmbedInline);

  md.renderer.rules.wiki_embed = function wikiEmbedRender(tokens, idx) {
    const meta = tokens[idx].meta || {};
    if (meta.kind === "video") return videoEmbedHtml(meta.url);
    return linkEmbedHtml(meta.url, meta.title);
  };
}

export async function createWikiMarkdown() {
  const markdownit = (await import("https://esm.sh/markdown-it@14.1.0")).default;
  const texmath = (await import("https://esm.sh/markdown-it-texmath@1.0.0")).default;
  const katex = (await import("https://esm.sh/katex@0.16.9")).default;
  return markdownit({ html: false, linkify: true, breaks: true })
    .use(texmath, {
      engine: katex,
      delimiters: ["brackets", "dollars"],
      katexOptions: { throwOnError: false, strict: false },
    })
    .use(wikiEmbedPlugin)
    .use(wikiImageWidthPlugin);
}

export function buildVideoEmbedMarkdown(url) {
  const trimmed = String(url || "").trim();
  if (!trimmed) return "";
  return `@[video](${trimmed})`;
}

export function buildLinkEmbedMarkdown(url, title) {
  const trimmed = String(url || "").trim();
  if (!trimmed) return "";
  const t = String(title || "").trim();
  if (t) {
    const escaped = t.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    return `@[link](${trimmed} "${escaped}")`;
  }
  return `@[link](${trimmed})`;
}

/** Optional image title: "width=400" sets rendered width in pixels. */
export function wikiImageWidthPlugin(md) {
  const defaultRender =
    md.renderer.rules.image ||
    function imageRender(tokens, idx, options, env, self) {
      return self.renderToken(tokens, idx, options);
    };

  md.renderer.rules.image = function imageRenderWithWidth(tokens, idx, options, env, self) {
    const token = tokens[idx];
    const title = token.attrGet("title") || "";
    const match = /^width=(\d+)$/.exec(title.trim());
    if (match) {
      token.attrSet("width", match[1]);
      token.attrSet("style", `width:${match[1]}px;max-width:100%;height:auto;`);
      token.attrSet("title", null);
    }
    return defaultRender(tokens, idx, options, env, self);
  };
}

export async function uploadWikiImage(file) {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch("/api/wiki/manual/upload-image", {
    method: "POST",
    body: form,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function uploadWikiVideo(file) {
  const form = new FormData();
  form.append("file", file);
  const r = await fetch("/api/wiki/manual/upload-video", {
    method: "POST",
    body: form,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

/** True when the user pressed Ctrl/Cmd+K or Ctrl/Cmd+I (link shortcut). */
export function isLinkShortcutKey(event) {
  if (!event || (!event.ctrlKey && !event.metaKey)) return false;
  const key = String(event.key || "").toLowerCase();
  return key === "i" || key === "k";
}

/** Read a non-empty text selection from a frame/window. */
export function getWindowSelection(win) {
  try {
    const sel = win && win.getSelection();
    if (!sel || !sel.rangeCount) return null;
    const text = sel.toString();
    if (!text.trim()) return null;
    let range = null;
    try {
      range = sel.getRangeAt(0).cloneRange();
    } catch (_) {}
    return { text, range, window: win };
  } catch (_) {
    return null;
  }
}

/**
 * Listen for Ctrl/Cmd+K or Ctrl/Cmd+I inside a same-origin iframe.
 * Keyboard focus stays in the iframe while editing, so parent listeners never run.
 */
export function attachIframeLinkShortcut(frameEl, onOpenLinkModal) {
  if (!frameEl || typeof onOpenLinkModal !== "function") {
    return () => {};
  }

  let detachFrame = null;

  function bindFrame() {
    if (typeof detachFrame === "function") detachFrame();
    detachFrame = null;
    try {
      const win = frameEl.contentWindow;
      const doc = frameEl.contentDocument;
      if (!win || !doc) return;
      doc.designMode = "on";

      const onKeyDown = (ev) => {
        if (!isLinkShortcutKey(ev)) return;
        const ps = getWindowSelection(win);
        if (!ps) return;
        ev.preventDefault();
        ev.stopPropagation();
        onOpenLinkModal(ps);
      };

      win.addEventListener("keydown", onKeyDown, true);
      doc.addEventListener("keydown", onKeyDown, true);
      detachFrame = () => {
        win.removeEventListener("keydown", onKeyDown, true);
        doc.removeEventListener("keydown", onKeyDown, true);
      };
    } catch (_) {}
  }

  frameEl.addEventListener("load", bindFrame);
  try {
    if (frameEl.contentDocument && frameEl.contentDocument.readyState === "complete") {
      bindFrame();
    }
  } catch (_) {}

  return () => {
    frameEl.removeEventListener("load", bindFrame);
    if (typeof detachFrame === "function") detachFrame();
  };
}
