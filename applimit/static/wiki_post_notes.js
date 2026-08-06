/**
 * Post notes: Marked.js + MathJax + highlight.js
 *
 * 1. Protect math delimiters before Marked (prevents _ and * breaking LaTeX)
 * 2. Parse Markdown → HTML
 * 3. Restore math, highlight code, then MathJax.typesetPromise every update
 */

const MARKED_SCRIPT = "https://cdn.jsdelivr.net/npm/marked/marked.min.js";
const MATHJAX_SCRIPT = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js";
const HLJS_SCRIPT =
  "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js";
const HLJS_STYLE =
  "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css";

const MATH_PH_PREFIX = "APPLIMITMATH";

export function getMathJaxConfig() {
  return {
    tex: {
      inlineMath: [
        ["$", "$"],
        ["\\(", "\\)"],
      ],
      displayMath: [
        ["$$", "$$"],
        ["\\[", "\\]"],
      ],
      processEscapes: true,
      processEnvironments: true,
    },
    options: {
      skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      ignoreHtmlClass: "tex2jax_ignore",
      processHtmlClass: "tex2jax_process",
    },
    chtml: { fontCache: "global" },
    startup: { typeset: false },
  };
}

export function applyMathJaxConfig() {
  if (window.__postNotesMathJaxConfigured) return;
  window.__postNotesMathJaxConfigured = true;
  window.MathJax = getMathJaxConfig();
}

/** Hide math from Marked so GFM emphasis/rules do not break LaTeX. */
export function protectMathDelimiters(markdown) {
  const blocks = [];
  const ph = (original) => {
    const id = blocks.length;
    blocks.push(original);
    return `${MATH_PH_PREFIX}${id}END`;
  };

  let text = String(markdown || "");

  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, body) => ph(`$$${body}$$`));
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (_, body) => ph(`\\[${body}\\]`));
  text = text.replace(/\\\(([\s\S]*?)\\\)/g, (_, body) => ph(`\\(${body}\\)`));
  text = text.replace(/(?<!\$)\$(?!\$)([^\$\n]+?)\$/g, (_, body) => ph(`$${body}$`));

  return { text, blocks };
}

export function restoreMathDelimiters(html, blocks) {
  let out = String(html || "");
  blocks.forEach((original, id) => {
    const token = `${MATH_PH_PREFIX}${id}END`;
    out = out.split(token).join(original);
  });
  return out;
}

function waitForScript(el) {
  return new Promise((resolve, reject) => {
    if (el.dataset.loaded === "1") {
      resolve();
      return;
    }
    el.addEventListener(
      "load",
      () => {
        el.dataset.loaded = "1";
        resolve();
      },
      { once: true }
    );
    el.addEventListener("error", () => reject(new Error(`Failed to load ${el.src}`)), {
      once: true,
    });
  });
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      if (existing.dataset.loaded === "1") {
        resolve();
        return;
      }
      if (src.includes("mathjax") && window.MathJax?.startup?.promise) {
        window.MathJax.startup.promise
          .then(() => {
            existing.dataset.loaded = "1";
            resolve();
          })
          .catch(reject);
        return;
      }
      if (src.includes("marked") && window.marked) {
        existing.dataset.loaded = "1";
        resolve();
        return;
      }
      waitForScript(existing).then(resolve).catch(reject);
      return;
    }
    const el = document.createElement("script");
    el.src = src;
    el.async = false;
    el.onload = () => {
      el.dataset.loaded = "1";
      resolve();
    };
    el.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(el);
  });
}

function loadStylesheet(href) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`link[href="${href}"]`)) {
      resolve();
      return;
    }
    const el = document.createElement("link");
    el.rel = "stylesheet";
    el.href = href;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error(`Failed to load ${href}`));
    document.head.appendChild(el);
  });
}

function configureMarked() {
  if (!window.marked || window.__postNotesMarkedConfigured) return;
  window.__postNotesMarkedConfigured = true;
  marked.setOptions({
    gfm: true,
    breaks: true,
  });
}

let markedReady = null;
let mathJaxReady = null;

function ensureMarkedReady() {
  if (!markedReady) {
    markedReady = (async () => {
      applyMathJaxConfig();
      await loadScript(MARKED_SCRIPT);
      configureMarked();
    })();
  }
  return markedReady;
}

function ensureMathJaxReady() {
  if (!mathJaxReady) {
    mathJaxReady = (async () => {
      applyMathJaxConfig();
      await loadScript(MATHJAX_SCRIPT);
      if (window.MathJax?.startup?.promise) {
        await window.MathJax.startup.promise;
      }
    })();
  }
  return mathJaxReady;
}

export function ensurePostNotesLibs() {
  return Promise.all([ensureMarkedReady(), ensureMathJaxReady()]);
}

async function typesetMathIn(container) {
  await ensureMathJaxReady();
  const mj = window.MathJax;
  if (!mj?.typesetPromise) {
    throw new Error("MathJax failed to load. Check your network connection and refresh.");
  }
  try {
    await mj.typesetPromise([container]);
  } catch (err) {
    console.warn("MathJax typeset failed, retrying once:", err);
    if (mj.typesetClear) mj.typesetClear([container]);
    await mj.typesetPromise([container]);
  }
}

export async function renderPostNotes(container, markdown) {
  if (!container) return;

  await Promise.all([ensureMarkedReady(), ensureMathJaxReady()]);

  if (window.MathJax?.typesetClear) {
    window.MathJax.typesetClear([container]);
  }

  const { text, blocks } = protectMathDelimiters(markdown);
  const parsed = marked.parse(text);
  container.classList.remove("muted");
  container.innerHTML = restoreMathDelimiters(parsed, blocks);

  await loadStylesheet(HLJS_STYLE);
  await loadScript(HLJS_SCRIPT);
  container.querySelectorAll("pre code").forEach((block) => {
    if (window.hljs) window.hljs.highlightElement(block);
  });

  await typesetMathIn(container);
}
