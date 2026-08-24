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
    const text = selectedText();
    if (!text) {
      showSingularityToast("Select text first, then press Ctrl+Shift+1.", true);
      return;
    }
    event.preventDefault();
    savedSelection = text;
    armedUntil = Date.now() + 15000;
    showSingularityToast("Singularity anchor armed — left-click the selected text.");
  }
}, true);

document.addEventListener("click", (event) => {
  if (event.button !== 0 || Date.now() > armedUntil) return;
  const pageId = wikiPageId();
  if (!pageId || !savedSelection) return;
  event.preventDefault();
  event.stopPropagation();
  armedUntil = 0;
  chrome.runtime.sendMessage({
    type: "CREATE_CHAT_ANCHOR",
    pageId,
    selection: savedSelection,
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
