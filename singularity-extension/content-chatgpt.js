/**
 * Runs on chatgpt.com inside the Singularity side-panel iframe.
 * Storage goes through the service worker — iframe context blocks chrome.storage.
 */

const PANEL_FLAG = "singularity-panel-v1";

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function sessionGet(keys) {
  return chrome.runtime.sendMessage({ type: "SESSION_GET", keys });
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
  el.focus();

  if (el.tagName === "TEXTAREA") {
    el.value = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

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
let anchorJobRunning = false;

async function waitForConversationUrl(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (/^\/c\/[^/]+/.test(location.pathname)) {
      const cleanPath = location.pathname.replace(/^\/c\/(?:WEB%3A|WEB:)/i, "/c/");
      return `${location.origin}${cleanPath}`;
    }
    await sleep(250);
  }
  throw new Error("ChatGPT did not create a permanent conversation URL.");
}

async function processPendingChatAnchor() {
  if (!isPanelFrame() || anchorJobRunning || jobRunning) return;
  let pendingChatAnchor;
  try {
    ({ pendingChatAnchor } = await sessionGet("pendingChatAnchor"));
  } catch {
    return;
  }
  if (!pendingChatAnchor?.promptText || !pendingChatAnchor.startedAt) return;
  if (Date.now() - pendingChatAnchor.startedAt > 180000) {
    await sessionRemove("pendingChatAnchor");
    return;
  }

  // A blank ChatGPT page has no durable URL. Start one message so /c/<id> exists.
  if (/^\/c\/[^/]+/.test(location.pathname)) {
    location.assign(`https://chatgpt.com/?singularity=1&anchor=${pendingChatAnchor.startedAt}`);
    return;
  }

  anchorJobRunning = true;
  try {
    if (!(await waitForComposer())) throw new Error("ChatGPT composer not found. Sign in inside Singularity first.");
    const prompt = `Help me understand this wiki text:\n\n${pendingChatAnchor.promptText}`;
    chatActivity("typing", "Starting a new linked conversation…");
    if (!setComposerText(prompt)) throw new Error("Could not enter the selected text in ChatGPT.");
    await sleep(350);
    if (!clickSend()) throw new Error("Could not start the new ChatGPT conversation.");
    const chatUrl = await waitForConversationUrl();
    await chrome.runtime.sendMessage({
      type: "CHAT_ANCHOR_READY",
      chatUrl,
      startedAt: pendingChatAnchor.startedAt,
    });
  } catch (error) {
    await chrome.runtime.sendMessage({
      type: "JOB_FAILED",
      error: error instanceof Error ? error.message : String(error),
    }).catch(() => {});
  } finally {
    anchorJobRunning = false;
  }
}

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
  if (!isPanelFrame()) return;
  let data;
  try {
    data = await sessionGet(["pendingScreenshot", "pendingScreenshotAt"]);
  } catch {
    return;
  }
  if (!data.pendingScreenshot) return;
  if (Date.now() - (data.pendingScreenshotAt || 0) > 120000) return;

  const res = await fetch(data.pendingScreenshot);
  const blob = await res.blob();
  const file = new File([blob], "shot.png", { type: "image/png" });

  let ok = false;
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

  await chrome.runtime.sendMessage({ type: "SCREENSHOT_RESULT", ok });
}

function startPanelWatchers() {
  if (!isPanelFrame()) return;

  markPanelFrame();
  chrome.runtime.sendMessage({ type: "PANEL_READY" }).catch(() => {});

  processPendingJob();
  processPendingChatAnchor();
  processPendingScreenshot();

  const observer = new MutationObserver(() => {
    processPendingJob();
    processPendingChatAnchor();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  setInterval(() => {
    if (!jobRunning) processPendingJob();
    if (!anchorJobRunning) processPendingChatAnchor();
  }, 2000);
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "START_CHAT_ANCHOR") processPendingChatAnchor();
});

startPanelWatchers();
