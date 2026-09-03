/** Bridge user-initiated wiki actions into the Singularity service worker. */
(function () {
  const TOOLBAR_ID = "singularity-page-tools";

  function deepText(element) {
    if (!element) return "";
    const shadowText = element.shadowRoot ? element.shadowRoot.textContent : "";
    const childShadowText = [...element.querySelectorAll("*")]
      .map((child) => child.shadowRoot?.textContent || "")
      .join("\n");
    return [element.textContent || "", shadowText, childShadowText].filter(Boolean).join("\n");
  }

  function readablePageContent() {
    const selected = String(window.getSelection?.() || "").trim();
    if (selected) return selected.slice(0, 250000);
    const preferred = document.querySelector("main, article, [role='main']");
    return deepText(preferred || document.body)
      .replace(/\n{4,}/g, "\n\n\n")
      .trim()
      .slice(0, 250000);
  }

  function pageTitle() {
    const heading = document.querySelector("main h1, article h1, h1");
    return String(heading?.textContent || document.title || location.hostname || "Web page")
      .trim()
      .slice(0, 240);
  }

  function startPageMode(mode, setStatus) {
    const content = readablePageContent();
    if (!content) {
      setStatus("No readable page content found.", true);
      return;
    }
    setStatus(`Opening ${mode}…`);
    chrome.runtime.sendMessage({
      type: "START_PAGE_TEST",
      title: pageTitle(),
      content,
      pageUrl: location.href,
      mode,
    }).then((result) => {
      if (result?.ok === false) throw new Error(result.error || "Could not start the page session.");
      setStatus(`${mode[0].toUpperCase()}${mode.slice(1)} sent to Singularity.`);
    }).catch((error) => {
      setStatus(error instanceof Error ? error.message : String(error), true);
    });
  }

  function createPageToolbar() {
    if (!document.documentElement || document.getElementById(TOOLBAR_ID)) return;
    const host = document.createElement("div");
    host.id = TOOLBAR_ID;
    host.setAttribute("data-singularity-ui", "true");
    const root = host.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        :host { all: initial; }
        .bar {
          position: fixed; right: 18px; bottom: 18px; z-index: 2147483647;
          display: flex; align-items: center; gap: 7px; padding: 8px;
          color: #182033; background: rgba(255,255,255,.97);
          border: 1px solid #cbd5e1; border-radius: 12px;
          box-shadow: 0 8px 28px rgba(15,23,42,.2);
          font: 600 14px/1.2 system-ui, -apple-system, "Segoe UI", sans-serif;
        }
        .label { padding: 0 4px; white-space: nowrap; }
        button {
          all: unset; box-sizing: border-box; cursor: pointer; display: inline-flex;
          align-items: center; gap: 6px; min-height: 34px; padding: 7px 10px;
          color: #182033; background: #fff; border: 1px solid #cbd5e1;
          border-radius: 8px; white-space: nowrap;
        }
        button:hover, button:focus-visible { background: #f1f5f9; border-color: #64748b; }
        button:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
        .settings { width: 34px; justify-content: center; padding: 7px; }
        .status { position: absolute; right: 0; bottom: calc(100% + 7px); max-width: 340px;
          padding: 7px 10px; border-radius: 7px; color: #fff; background: #166534;
          box-shadow: 0 4px 14px rgba(15,23,42,.18); font-size: 12px; font-weight: 500; }
        .status.error { background: #991b1b; }
        .status[hidden] { display: none; }
        @media (max-width: 720px) {
          .bar { left: 8px; right: 8px; bottom: 8px; overflow-x: auto; }
          .label { display: none; }
        }
        @media print { .bar { display: none !important; } }
      </style>
      <div class="bar" role="toolbar" aria-label="Ask this page with Singularity">
        <span class="label">Ask page:</span>
        <button type="button" data-mode="recall" title="Ask recall questions about this page">🧠 Recall</button>
        <button type="button" data-mode="memorise" title="Create a memorisation session from this page">🗂️ Memorise</button>
        <button type="button" data-mode="maths" title="Ask mathematics questions about this page">∑ Maths</button>
        <button type="button" data-mode="notations" title="Explain notation used on this page">𝑥 Notation</button>
        <button type="button" class="settings" data-settings title="Singularity settings" aria-label="Singularity settings">⚙</button>
        <div class="status" role="status" aria-live="polite" hidden></div>
      </div>`;

    const status = root.querySelector(".status");
    let statusTimer;
    const setStatus = (message, error = false) => {
      clearTimeout(statusTimer);
      status.textContent = message;
      status.classList.toggle("error", error);
      status.hidden = false;
      statusTimer = setTimeout(() => { status.hidden = true; }, error ? 7000 : 3500);
    };
    root.querySelectorAll("[data-mode]").forEach((button) => {
      button.addEventListener("click", () => startPageMode(button.dataset.mode, setStatus));
    });
    root.querySelector("[data-settings]").addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "OPEN_INTEGRATION_SETTINGS" }).catch((error) => {
        setStatus(error instanceof Error ? error.message : String(error), true);
      });
    });
    document.documentElement.appendChild(host);
  }

  document.addEventListener("singularity:start-page-test", (event) => {
    const detail = event.detail || {};
    const renderedContent = deepText(document.querySelector("[data-wiki-test-content]"));
    const content = String(detail.content || renderedContent || "").slice(0, 250000);
    chrome.runtime.sendMessage({
      type: "START_PAGE_TEST",
      title: String(detail.title || document.title).slice(0, 240),
      content,
      pageUrl: String(detail.pageUrl || location.href),
      mode: ["recall", "memorise", "maths", "notations"].includes(detail.mode) ? detail.mode : "recall",
    }).then((result) => {
      document.dispatchEvent(new CustomEvent("singularity:start-page-test-result", { detail: result || { ok: true } }));
    }).catch((error) => {
      document.dispatchEvent(new CustomEvent("singularity:start-page-test-result", {
        detail: { ok: false, error: error instanceof Error ? error.message : String(error) },
      }));
    });
  });

  document.addEventListener("singularity:open-integration-settings", () => {
    chrome.runtime.sendMessage({ type: "OPEN_INTEGRATION_SETTINGS" }).catch(() => {});
  });

  createPageToolbar();
})();
