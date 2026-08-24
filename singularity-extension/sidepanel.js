const CHATGPT_PANEL_URL = "https://chatgpt.com/?singularity=1";
const frame = document.getElementById("chatgpt");
const statusEl = document.getElementById("status");
const wikiLink = document.getElementById("wiki-link");
const progressPanel = document.getElementById("progress-panel");
const progressStep = document.getElementById("progress-step");
const progressCount = document.getElementById("progress-count");
const progressFill = document.getElementById("progress-fill");
const progressActivity = document.getElementById("progress-activity");
const progressLog = document.getElementById("progress-log");

function setStatus(text) {
  statusEl.textContent = text;
}

function focusChatgptFrame() {
  try {
    frame.focus();
  } catch {
    /* ignore */
  }
  try {
    frame.contentWindow?.focus();
  } catch {
    /* cross-origin focus may fail until loaded */
  }
}

function renderJobProgress(jobStatus, activityDetail) {
  if (!jobStatus?.label) {
    progressPanel.classList.remove("is-active");
    return;
  }

  const activePhases = ["starting", "chatgpt", "wiki", "expansion"];
  const isActive = activePhases.includes(jobStatus.phase);
  progressPanel.classList.toggle("is-active", isActive || jobStatus.phase === "done");

  setStatus(jobStatus.label);
  progressStep.textContent = jobStatus.label;

  const step = jobStatus.expansionStep || 0;
  const total = jobStatus.expansionTotal || 0;
  if (total > 0) {
    progressCount.textContent = `${Math.min(step, total)} / ${total}`;
    progressFill.style.width = `${Math.round((Math.min(step, total) / total) * 100)}%`;
  } else if (jobStatus.phase === "expansion" || jobStatus.phase === "chatgpt") {
    progressCount.textContent = "…";
    progressFill.style.width = "35%";
  } else {
    progressCount.textContent = "";
    progressFill.style.width = jobStatus.phase === "done" ? "100%" : "0%";
  }

  if (activityDetail) {
    progressActivity.textContent = activityDetail;
  } else if (jobStatus.phase === "chatgpt") {
    progressActivity.textContent = "ChatGPT is replying in the panel below ↓";
  } else if (jobStatus.phase === "expansion") {
    progressActivity.textContent = "Watch ChatGPT below — each term/concept gets its own query";
  } else {
    progressActivity.textContent = "";
  }

  const log = jobStatus.log || [];
  progressLog.innerHTML = log
    .slice(-8)
    .reverse()
    .map((line) => `<li>${escapeHtml(line)}</li>`)
    .join("");

  if (jobStatus.phase === "done" && jobStatus.url) {
    wikiLink.href = jobStatus.url;
    wikiLink.textContent = jobStatus.label?.includes("index") ? "Open index" : "Open page";
    wikiLink.hidden = false;
  }
  if (jobStatus.phase === "failed") {
    wikiLink.hidden = true;
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function syncJobStatusFromStorage() {
  const { jobStatus } = await chrome.storage.session.get("jobStatus");
  renderJobProgress(jobStatus || null);
}

frame.addEventListener("load", () => {
  setStatus("Loading ChatGPT…");
  setTimeout(syncJobStatusFromStorage, 500);
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "session" && changes.jobStatus) {
    renderJobProgress(changes.jobStatus.newValue || null);
  }
});

setInterval(syncJobStatusFromStorage, 2000);

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "FOCUS_PANEL_FRAME") {
    focusChatgptFrame();
  }
  if (msg.type === "CHATGPT_ACTIVITY") {
    focusChatgptFrame();
    chrome.storage.session.get("jobStatus").then(({ jobStatus }) => {
      const detail =
        msg.detail ||
        (msg.activity === "typing" ? "Typing prompt into ChatGPT…" : "") ||
        (msg.activity === "waiting" ? "Waiting for ChatGPT reply…" : "") ||
        (msg.activity === "copy" ? "Copying response…" : "") ||
        msg.activity ||
        "";
      renderJobProgress(jobStatus, detail);
    });
  }
  if (msg.type === "ATTACH_SCREENSHOT") setStatus("Attaching screenshot…");
  if (msg.type === "ATTACH_DONE") {
    setStatus(msg.ok ? "Screenshot attached" : "Could not attach screenshot");
  }
  if (msg.type === "CHATGPT_READY") {
    chrome.storage.session.get("jobStatus").then(({ jobStatus }) => {
      if (jobStatus?.phase === "starting" || jobStatus?.phase === "chatgpt") {
        renderJobProgress(jobStatus, "ChatGPT ready — processing…");
      }
    });
  }
  if (msg.type === "JOB_STARTED") {
    focusChatgptFrame();
    renderJobProgress(
      { phase: "starting", label: msg.label || "Working…", log: [msg.label || "Working…"] },
      "Sending your selection to ChatGPT…",
    );
  }
  if (msg.type === "JOB_PROGRESS") {
    focusChatgptFrame();
    chrome.storage.session.get("jobStatus").then(({ jobStatus }) => {
      renderJobProgress(jobStatus || { phase: msg.phase || "working", label: msg.label, log: msg.log });
    });
  }
  if (msg.type === "JOB_FAILED") {
    setStatus(msg.error || "Failed");
    progressPanel.classList.add("is-active");
    progressStep.textContent = msg.error || "Failed";
    progressActivity.textContent = "";
    wikiLink.hidden = true;
  }
  if (msg.type === "EXPANSION_DONE") {
    setStatus(`Expansion done — ${msg.pageCount || ""} pages`);
    if (msg.indexUrl) {
      wikiLink.href = msg.indexUrl;
      wikiLink.textContent = "Open index";
      wikiLink.hidden = false;
    }
    syncJobStatusFromStorage();
  }
  if (msg.type === "WIKI_CREATED") {
    if (msg.expanding) {
      renderJobProgress(
        {
          phase: "expansion",
          label: "Answer saved — expansion starting…",
          log: ["Answer page saved", "Starting expansion…"],
          expansionStep: 0,
        },
        "Keep this panel open. ChatGPT will run many queries below.",
      );
      if (msg.url) {
        wikiLink.href = msg.url;
        wikiLink.textContent = "Open answer";
        wikiLink.hidden = false;
      }
    } else {
      setStatus("Wiki page created");
      if (msg.url) {
        wikiLink.href = msg.url;
        wikiLink.textContent = msg.parentUrl ? "Open answer" : "Open page";
        wikiLink.hidden = false;
      }
    }
  }
});

document.getElementById("reload").addEventListener("click", () => {
  setStatus("Reloading…");
  frame.src = CHATGPT_PANEL_URL;
});

document.getElementById("open-tab").addEventListener("click", () => {
  chrome.tabs.create({ url: "https://chatgpt.com/" });
});

document.getElementById("options").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

document.getElementById("send-shot").addEventListener("click", async () => {
  setStatus("Capturing…");
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.windowId) throw new Error("No active tab");
    const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
      format: "png",
      quality: 92,
    });
    await chrome.storage.session.set({
      pendingScreenshot: dataUrl,
      pendingScreenshotAt: Date.now(),
    });
    setStatus("Attaching screenshot…");
    chrome.runtime.sendMessage({ type: "FLUSH_PENDING_SCREENSHOT" });
  } catch (e) {
    setStatus(String(e));
  }
});

syncJobStatusFromStorage();
chrome.runtime.sendMessage({ type: "PANEL_OPENED" }).catch(() => {});
