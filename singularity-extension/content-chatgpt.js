/**
 * Runs on chatgpt.com inside the Singularity side-panel iframe.
 * Storage goes through the service worker — iframe context blocks chrome.storage.
 */

const PANEL_FLAG = "singularity-panel-v1";

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function sessionGet(keys) {
  const response = await chrome.runtime.sendMessage({ type: "SESSION_GET", keys });
  return response || {};
}

function sessionSet(data) {
  return chrome.runtime.sendMessage({ type: "SESSION_SET", data });
}

function sessionRemove(keys) {
  return chrome.runtime.sendMessage({ type: "SESSION_REMOVE", keys });
}

function markPanelFrame() {
  try {
    sessionStorage.setItem(PANEL_FLAG, "1");
  } catch {
    /* ignore */
  }
}

function isPanelFrame() {
  if (window === window.top) return false;
  try {
    if (new URLSearchParams(window.location.search).get("singularity") === "1") {
      markPanelFrame();
      return true;
    }
    return sessionStorage.getItem(PANEL_FLAG) === "1";
  } catch {
    return false;
  }
}

function findComposer() {
  return (
    document.querySelector('div[contenteditable="true"]#prompt-textarea') ||
    document.querySelector('div[contenteditable="true"][data-testid="prompt-textarea"]') ||
    document.querySelector('textarea#prompt-textarea') ||
    document.querySelector('div[contenteditable="true"][role="textbox"]') ||
    document.querySelector('div[contenteditable="true"]')
  );
}

function findSendButton() {
  return (
    document.querySelector('button[data-testid="send-button"]:not([disabled])') ||
    document.querySelector('button[data-testid="send-button"]') ||
    document.querySelector('button[aria-label="Send prompt"]') ||
    document.querySelector('button[aria-label*="Send"]')
  );
}

function isGenerating() {
  return !!(
    document.querySelector('[data-testid="stop-button"]') ||
    document.querySelector('button[aria-label*="Stop"]')
  );
}

function getAssistantMessages() {
  return [...document.querySelectorAll('[data-message-author-role="assistant"]')];
}

function findCopyButton(messageNode) {
  if (!messageNode) return null;
  const assistant =
    messageNode.closest('[data-message-author-role="assistant"]') ||
    messageNode.closest("[data-message-id]") ||
    messageNode;
  const article = assistant.closest("article") || assistant;
  const roots = new Set([assistant, article, article?.parentElement, messageNode]);

  let sib = assistant.nextElementSibling;
  for (let i = 0; i < 4 && sib; i++) {
    roots.add(sib);
    sib = sib.nextElementSibling;
  }

  for (const scope of roots) {
    if (!scope?.querySelectorAll) continue;
    for (const btn of scope.querySelectorAll("button")) {
      const testid = (btn.getAttribute("data-testid") || "").toLowerCase();
      const label = (btn.getAttribute("aria-label") || "").toLowerCase();
      if (testid.includes("copy") || label === "copy" || label.startsWith("copy ")) {
        return btn;
      }
    }
  }
  return null;
}

async function requestPanelFocus() {
  await chrome.runtime.sendMessage({ type: "FOCUS_PANEL_FRAME" }).catch(() => {});
  await sleep(180);
  try {
    window.focus();
  } catch {
    /* ignore */
  }
}

async function revealMessageActions(messageNode) {
  const hit =
    messageNode.querySelector(".markdown, .prose, [class*='markdown']") ||
    messageNode;
  hit.scrollIntoView({ block: "center", behavior: "instant" });
  for (const type of ["mouseenter", "mouseover", "mousemove"]) {
    hit.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
  }
  await sleep(220);
}

async function clickCopyAndCapture(copyBtn) {
  let plain = "";
  let html = "";
  const onCopy = (e) => {
    const p = e.clipboardData?.getData("text/plain");
    const h = e.clipboardData?.getData("text/html");
    if (p) plain = p;
    if (h) html = h;
  };
  document.addEventListener("copy", onCopy, true);

  copyBtn.focus({ preventScroll: true });
  copyBtn.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
  copyBtn.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
  copyBtn.dispatchEvent(new PointerEvent("pointerup", { bubbles: true }));
  copyBtn.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  copyBtn.click();
  await sleep(900);

  document.removeEventListener("copy", onCopy, true);

  if (plain.trim() && looksLikeMarkdown(plain)) return plain.trim();

  if (html.trim()) {
    const fromHtml = markdownFromHtmlClipboard(html);
    if (fromHtml) return fromHtml;
  }

  if (plain.trim()) return plain.trim();

  try {
    const clip = (await navigator.clipboard.readText()).trim();
    if (clip) return clip;
  } catch {
    /* focus-dependent */
  }
  return "";
}

function looksLikeMarkdown(text) {
  if (!text) return false;
  return /(^|\n)(#{1,6}\s|[-*+]\s|\d+\.\s)|\*\*[^*]+\*\*|\\[\[(]/.test(text);
}

function katexToLatex(el) {
  const ann = el.querySelector?.('annotation[encoding="application/x-tex"]');
  if (ann?.textContent) {
    const t = ann.textContent.trim();
    return el.classList?.contains("katex-display")
      ? `\n\n\\[\n${t}\n\\]\n\n`
      : `\\(${t}\\)`;
  }
  return (el.textContent || "").trim();
}

function childrenInline(el) {
  let out = "";
  for (const child of el.childNodes) out += inlineMarkdown(child);
  return out;
}

function inlineMarkdown(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent.replace(/\u00a0/g, " ");
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return "";
  const el = node;
  const tag = el.tagName.toLowerCase();
  if (tag === "br") return "\n";
  if (el.classList?.contains("katex") || el.classList?.contains("katex-display")) {
    return katexToLatex(el);
  }
  if (tag === "strong" || tag === "b") return `**${childrenInline(el).trim()}**`;
  if (tag === "em" || tag === "i") return `*${childrenInline(el).trim()}*`;
  if (tag === "code") return `\`${el.textContent}\``;
  if (tag === "a") {
    const href = el.getAttribute("href") || "";
    return `[${childrenInline(el).trim()}](${href})`;
  }
  return childrenInline(el);
}

function listItemText(li) {
  const ps = li.querySelectorAll(":scope > p");
  if (ps.length) return [...ps].map((p) => childrenInline(p).trim()).join(" ");
  return childrenInline(li).trim();
}

function blockMarkdown(el) {
  if (!el?.tagName) return "";
  const tag = el.tagName.toLowerCase();

  if (el.classList?.contains("katex-display")) {
    return katexToLatex(el);
  }

  switch (tag) {
    case "h1":
      return `\n\n# ${childrenInline(el).trim()}\n\n`;
    case "h2":
      return `\n\n## ${childrenInline(el).trim()}\n\n`;
    case "h3":
      return `\n\n### ${childrenInline(el).trim()}\n\n`;
    case "h4":
      return `\n\n#### ${childrenInline(el).trim()}\n\n`;
    case "p":
      return `\n\n${childrenInline(el).trim()}\n\n`;
    case "ul":
      return (
        "\n\n" +
        [...el.children]
          .filter((c) => c.tagName === "LI")
          .map((li) => `- ${listItemText(li)}`)
          .join("\n") +
        "\n\n"
      );
    case "ol":
      return (
        "\n\n" +
        [...el.children]
          .filter((c) => c.tagName === "LI")
          .map((li, i) => `${i + 1}. ${listItemText(li)}`)
          .join("\n") +
        "\n\n"
      );
    case "pre": {
      const code = el.querySelector("code");
      const lang = code?.className?.match(/language-(\w+)/)?.[1] || "";
      return `\n\n\`\`\`${lang}\n${(code || el).textContent.trim()}\n\`\`\`\n\n`;
    }
    case "blockquote":
      return (
        "\n\n" +
        childrenInline(el)
          .trim()
          .split("\n")
          .map((l) => `> ${l}`)
          .join("\n") +
        "\n\n"
      );
    case "hr":
      return "\n\n---\n\n";
    case "div":
    case "section":
    case "article":
    case "span":
      if (el.classList?.contains("katex")) return katexToLatex(el);
      return [...el.childNodes]
        .map((c) =>
          c.nodeType === Node.ELEMENT_NODE
            ? blockMarkdown(c)
            : c.nodeType === Node.TEXT_NODE && c.textContent.trim()
              ? `${c.textContent.trim()}\n\n`
              : "",
        )
        .join("");
    default:
      return [...el.childNodes]
        .map((c) => (c.nodeType === Node.ELEMENT_NODE ? blockMarkdown(c) : ""))
        .join("");
  }
}

function getMessageMarkdownRoot(messageNode) {
  return (
    messageNode.querySelector(".markdown.prose") ||
    messageNode.querySelector(".markdown") ||
    messageNode.querySelector(".prose") ||
    messageNode.querySelector("[class*='markdown']") ||
    messageNode
  );
}

function extractMarkdownFromMessage(messageNode) {
  const root = getMessageMarkdownRoot(messageNode);
  const parts = [];
  for (const child of root.childNodes) {
    if (child.nodeType === Node.ELEMENT_NODE) {
      parts.push(blockMarkdown(child));
    } else if (child.nodeType === Node.TEXT_NODE && child.textContent.trim()) {
      parts.push(`${child.textContent.trim()}\n\n`);
    }
  }
  return parts.join("").replace(/\n{3,}/g, "\n\n").trim();
}

function markdownFromHtmlClipboard(html) {
  try {
    const doc = new DOMParser().parseFromString(html, "text/html");
    const body = doc.body;
    if (!body) return "";
    const md = extractMarkdownFromMessage(body);
    return md.trim();
  } catch {
    return "";
  }
}

function extractMessageText(node) {
  if (!node) return "";
  const md =
    node.querySelector(".markdown, .prose, [class*='markdown']") ||
    node.querySelector("[class*='agent-turn']");
  return (md || node).innerText.trim();
}

function setComposerText(text) {
  const el = findComposer();
  if (!el) return false;

  if (el.tagName === "TEXTAREA") {
    el.value = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  el.focus({ preventScroll: true });
  try {
    document.execCommand("selectAll", false, null);
    document.execCommand("insertText", false, text);
  } catch {
    el.textContent = text;
  }
  el.dispatchEvent(
    new InputEvent("input", {
      bubbles: true,
      inputType: "insertText",
      data: text,
    }),
  );
  return true;
}

function clickSend() {
  const btn = findSendButton();
  if (!btn || btn.disabled) return false;
  btn.click();
  return true;
}

async function waitForComposer(timeoutMs = 90000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (findComposer()) return true;
    await sleep(800);
  }
  return false;
}

async function waitForAssistantReply(beforeCount, timeoutMs = 180000) {
  const start = Date.now();
  let lastMsg = null;
  let lastText = "";
  let stable = 0;

  while (Date.now() - start < timeoutMs) {
    const msgs = getAssistantMessages();
    if (msgs.length > beforeCount && !isGenerating()) {
      const msg = msgs[msgs.length - 1];
      const text = extractMessageText(msg);
      if (text.length > 0) {
        lastMsg = msg;
        if (text === lastText) stable += 1;
        else {
          stable = 0;
          lastText = text;
        }
        if (stable >= 3) return msg;
      }
    }
    await sleep(500);
  }
  throw new Error("Timed out waiting for ChatGPT reply.");
}

async function copyReplyViaButton(messageNode) {
  const fromDom = extractMarkdownFromMessage(messageNode);
  let fromCopy = "";

  for (let attempt = 0; attempt < 3; attempt++) {
    await requestPanelFocus();
    await revealMessageActions(messageNode);

    const copyBtn = findCopyButton(messageNode);
    if (!copyBtn) {
      await sleep(350);
      continue;
    }

    fromCopy = await clickCopyAndCapture(copyBtn);
    if (fromCopy && looksLikeMarkdown(fromCopy)) return fromCopy;
    if (fromCopy) break;
  }

  if (fromCopy && looksLikeMarkdown(fromCopy)) return fromCopy;
  if (fromDom.length > 20) return fromDom;
  if (fromCopy) return fromCopy;
  if (fromDom) return fromDom;

  const fallback = extractMessageText(messageNode);
  if (fallback) return fallback;
  throw new Error(
    "Copy failed (document lost focus). Click inside the Singularity panel, then retry Send to Singularity.",
  );
}

function chatActivity(activity, detail) {
  chrome.runtime
    .sendMessage({ type: "CHATGPT_ACTIVITY", activity, detail: detail || "" })
    .catch(() => {});
}

async function promptChatGPT(prompt) {
  if (!(await waitForComposer())) {
    throw new Error("ChatGPT composer not found. Log in inside the Singularity panel first.");
  }
  const before = getAssistantMessages().length;
  chatActivity("typing", "Typing prompt into ChatGPT…");
  if (!setComposerText(prompt)) {
    throw new Error("Could not enter text in ChatGPT composer.");
  }
  await sleep(400);
  if (!clickSend()) {
    throw new Error("Could not click Send. Is ChatGPT still loading?");
  }
  chatActivity("waiting", "Waiting for ChatGPT reply…");
  const replyNode = await waitForAssistantReply(before);
  await requestPanelFocus();
  chatActivity("copy", "Copying formatted response…");
  return copyReplyViaButton(replyNode);
}

let jobRunning = false;
let copyRunning = false;
let screenshotRunning = false;

async function processPendingJob() {
  if (!isPanelFrame() || jobRunning) return;

  let pendingJob;
  try {
    ({ pendingJob } = await sessionGet("pendingJob"));
  } catch {
    return;
  }
  if (!pendingJob?.prompt || !pendingJob.jobStartedAt) return;
  if (Date.now() - pendingJob.jobStartedAt > 180000) return;

  jobRunning = true;
  try {
    const text = await promptChatGPT(pendingJob.prompt);
    await sessionRemove("pendingJob");
    await chrome.runtime.sendMessage({
      type: "PROMPT_RESULT",
      ok: true,
      text,
      jobStartedAt: pendingJob.jobStartedAt,
    });
  } catch (e) {
    await sessionRemove("pendingJob");
    await chrome.runtime.sendMessage({
      type: "PROMPT_RESULT",
      ok: false,
      error: e instanceof Error ? e.message : String(e),
      jobStartedAt: pendingJob.jobStartedAt,
    });
  } finally {
    jobRunning = false;
  }
}

async function processPendingScreenshot() {
  if (!isPanelFrame() || screenshotRunning) return;
  let data;
  try {
    data = await sessionGet(["pendingScreenshot", "pendingScreenshotAt"]);
  } catch {
    return;
  }
  if (!data.pendingScreenshot) return;
  if (Date.now() - (data.pendingScreenshotAt || 0) > 120000) return;

  screenshotRunning = true;
  let ok = false;
  try {
    const res = await fetch(data.pendingScreenshot);
    if (!res.ok) throw new Error(`Could not load screenshot (${res.status})`);
    const blob = await res.blob();
    const file = new File([blob], "shot.png", { type: "image/png" });

    for (let i = 0; i < 24; i++) {
      const input = document.querySelector('input[type="file"]');
      if (input) {
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        ok = true;
        break;
      }
      await sleep(500);
    }
  } catch {
    ok = false;
  } finally {
    await chrome.runtime.sendMessage({ type: "SCREENSHOT_RESULT", ok }).catch(() => {});
    await sessionRemove(["pendingScreenshot", "pendingScreenshotAt"]).catch(() => {});
    screenshotRunning = false;
  }
}

let floatingScreenshotScheduled = false;

function installFloatingScreenshotButton() {
  if (!isPanelFrame() || document.getElementById("singularity-floating-shot-host") || floatingScreenshotScheduled) return;
  if (!document.documentElement) return;

  floatingScreenshotScheduled = true;
  setTimeout(() => {
    floatingScreenshotScheduled = false;
    if (document.getElementById("singularity-floating-shot-host") || !document.documentElement) return;

    // Keep extension UI outside ChatGPT's React-managed body. Injecting a node
    // into that application tree during hydration can trigger React error #418.
    const host = document.createElement("div");
    host.id = "singularity-floating-shot-host";
    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `
      :host { all: initial; }
      button {
        position: fixed; right: 18px; bottom: 92px; z-index: 2147483647;
        width: 44px; height: 44px; border: 1px solid rgba(255,255,255,.2);
        border-radius: 999px; background: #10a37f; color: #fff;
        box-shadow: 0 6px 20px rgba(0,0,0,.3); cursor: pointer;
        font: 20px/40px "Segoe UI Emoji", "Segoe UI", sans-serif; padding: 0;
        transition: transform .12s ease, opacity .12s ease;
      }
      button:hover { transform: scale(1.06); }
      button:disabled { cursor: wait; opacity: .82; }
    `;
    const button = document.createElement("button");
    button.id = "singularity-floating-shot";
    button.type = "button";
    button.textContent = "📷";
    button.title = "Capture the active tab and attach it to this chat";
    button.setAttribute("aria-label", "Capture active tab screenshot");
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      button.disabled = true;
      button.textContent = "…";
      button.title = "Capturing screenshot…";
      try {
        const result = await chrome.runtime.sendMessage({ type: "CAPTURE_SCREENSHOT_FROM_CHAT" });
        if (!result?.ok) throw new Error(result?.error || "Could not attach screenshot");
        button.textContent = "✓";
        button.title = "Screenshot attached";
      } catch (error) {
        button.textContent = "!";
        button.title = error instanceof Error ? error.message : String(error);
      } finally {
        setTimeout(() => {
          button.disabled = false;
          button.textContent = "📷";
          button.title = "Capture the active tab and attach it to this chat";
        }, 1800);
      }
    });

    shadow.append(style, button);
    document.documentElement.appendChild(host);
  }, document.readyState === "complete" ? 500 : 2500);
}

async function processCopyRequest() {
  if (!isPanelFrame() || copyRunning) return;
  const data = await sessionGet("copyRequest").catch(() => ({}));
  const copyRequest = data?.copyRequest;
  if (!copyRequest?.id || Date.now() - (copyRequest.at || 0) > 30000) return;
  copyRunning = true;
  try {
    const messages = getAssistantMessages();
    const latest = messages[messages.length - 1];
    if (!latest) throw new Error("No ChatGPT response is available yet.");
    const text = await copyReplyViaButton(latest);
    await sessionSet({ copyResult: { id: copyRequest.id, ok: true, text } });
  } catch (error) {
    await sessionSet({
      copyResult: {
        id: copyRequest.id,
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      },
    });
  } finally {
    copyRunning = false;
  }
}

function startPanelWatchers() {
  if (!isPanelFrame()) return;

  markPanelFrame();
  chrome.runtime.sendMessage({ type: "PANEL_READY" }).catch(() => {});

  processPendingJob();
  processPendingScreenshot();
  installFloatingScreenshotButton();

  const observer = new MutationObserver(() => {
    processPendingJob();
    processPendingScreenshot();
    installFloatingScreenshotButton();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  setInterval(() => {
    if (!jobRunning) processPendingJob();
    processPendingScreenshot();
    processCopyRequest();
    installFloatingScreenshotButton();
  }, 2000);
}

startPanelWatchers();
