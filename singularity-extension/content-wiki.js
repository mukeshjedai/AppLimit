/** Ctrl+Shift+1 arms the next left click to create a Singularity chat anchor. */
let armedUntil = 0;
let savedSelection = "";

function wikiPageId() {
  const match = location.pathname.match(/^\/wiki\/([a-zA-Z0-9_-]+)\/?$/);
  return match?.[1] || "";
}

function selectedText() {
  return (window.getSelection()?.toString() || "").trim();
}

function clickTextContext(event) {
  let node = null;
  let offset = 0;
  if (document.caretPositionFromPoint) {
    const position = document.caretPositionFromPoint(event.clientX, event.clientY);
    node = position?.offsetNode || null;
    offset = position?.offset || 0;
  } else if (document.caretRangeFromPoint) {
    const range = document.caretRangeFromPoint(event.clientX, event.clientY);
    node = range?.startContainer || null;
    offset = range?.startOffset || 0;
  }
  if (node?.nodeType !== Node.TEXT_NODE) return null;
  const value = node.nodeValue || "";
  const before = value.slice(Math.max(0, offset - 160), offset);
  const after = value.slice(offset, offset + 160);
  const nearby = value.trim().slice(0, 500);
  if (!before && !after) return null;
  return { before, after, nearby };
}

function showSingularityToast(message, error = false) {
  let toast = document.getElementById("singularity-chat-anchor-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "singularity-chat-anchor-toast";
    Object.assign(toast.style, {
      position: "fixed", right: "18px", bottom: "18px", zIndex: "2147483647",
      padding: "10px 14px", borderRadius: "8px", color: "white",
      font: "13px/1.4 Segoe UI, sans-serif", boxShadow: "0 8px 24px #0005",
    });
    document.documentElement.appendChild(toast);
  }
  toast.style.background = error ? "#b91c1c" : "#5b21b6";
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showSingularityToast.timer);
  showSingularityToast.timer = setTimeout(() => { toast.hidden = true; }, 5000);
}

document.addEventListener("keydown", (event) => {
  if (event.ctrlKey && event.shiftKey && event.code === "Digit1") {
    event.preventDefault();
    savedSelection = selectedText();
    armedUntil = Date.now() + 15000;
    showSingularityToast(
      savedSelection
        ? "Singularity anchor armed — left-click the selected text."
        : "Singularity anchor armed — left-click where the anchor should appear.",
    );
  }
}, true);

document.addEventListener("click", (event) => {
  if (event.button !== 0 || Date.now() > armedUntil) return;
  const pageId = wikiPageId();
  if (!pageId) return;
  const context = savedSelection ? null : clickTextContext(event);
  if (!savedSelection && !context) {
    showSingularityToast("Click directly beside text in the wiki content.", true);
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  armedUntil = 0;
  chrome.runtime.sendMessage({
    type: "CREATE_CHAT_ANCHOR",
    pageId,
    selection: savedSelection,
    contextBefore: context?.before || "",
    contextAfter: context?.after || "",
    promptText: savedSelection || context?.nearby || "This wiki location",
    pageUrl: location.href,
  }).then((result) => {
    if (!result?.ok) showSingularityToast(result?.error || "Could not start Singularity chat.", true);
    else showSingularityToast("Creating a new Singularity chat…");
  }).catch((error) => showSingularityToast(String(error), true));
}, true);

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "CHAT_ANCHOR_SAVED") {
    showSingularityToast("Chat anchor saved. Refreshing page…");
    setTimeout(() => location.reload(), 500);
  }
  if (message.type === "CHAT_ANCHOR_FAILED") {
    showSingularityToast(message.error || "Chat anchor failed.", true);
  }
});
