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
const mediaPanel = document.getElementById("media-panel");
const audioPlayer = document.getElementById("audio-player");
const recordingState = document.getElementById("recording-state");
const recordAudioButton = document.getElementById("record-audio");
let mediaRecorder = null;
let recordedAudioUrl = "";
let capturedAudioStream = null;
let monitorAudioContext = null;

function timestampName(prefix, extension) {
  return `Singularity/${prefix}-${new Date().toISOString().replace(/[:.]/g, "-")}.${extension}`;
}

async function hasPermission(permission) {
  return chrome.permissions.contains({ permissions: [permission] });
}

function openPermissionsPage(message) {
  setStatus(message || "Grant media permissions first");
  chrome.tabs.create({ url: chrome.runtime.getURL("permissions.html") });
}

async function downloadUrl(url, filename) {
  if (!(await hasPermission("downloads"))) {
    openPermissionsPage("Grant Downloads permission first");
    return false;
  }
  await chrome.downloads.download({ url, filename, saveAs: true });
  return true;
}

function getTabAudioStreamId(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabCapture.getMediaStreamId({ targetTabId: tabId }, (streamId) => {
      const error = chrome.runtime.lastError;
      if (error || !streamId) reject(new Error(error?.message || "Could not capture tab audio."));
      else resolve(streamId);
    });
  });
}

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

document.getElementById("permissions").addEventListener("click", () => {
  chrome.tabs.create({ url: chrome.runtime.getURL("permissions.html") });
});

document.getElementById("send-shot").addEventListener("click", async () => {
  setStatus("Capturing…");
  try {
    const result = await chrome.runtime.sendMessage({ type: "CAPTURE_SCREENSHOT_FROM_CHAT" });
    if (!result?.ok) throw new Error(result?.error || "Could not capture screenshot");
    setStatus("Screenshot attached");
  } catch (e) {
    setStatus(String(e));
  }
});

document.getElementById("save-shot").addEventListener("click", async () => {
  setStatus("Capturing screenshot…");
  try {
    if (!(await hasPermission("downloads"))) {
      openPermissionsPage("Grant Downloads permission to save screenshots");
      return;
    }
    const result = await chrome.runtime.sendMessage({ type: "CAPTURE_SCREENSHOT_DATA" });
    if (!result?.ok || !result.dataUrl) throw new Error(result?.error || "Could not capture screenshot");
    await downloadUrl(result.dataUrl, timestampName("screenshot", "png"));
    setStatus("Screenshot download started");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

recordAudioButton.addEventListener("click", async () => {
  if (mediaRecorder?.state === "recording") {
    mediaRecorder.stop();
    recordAudioButton.textContent = "Record";
    return;
  }
  setStatus("Starting tab audio recording…");
  try {
    if (!(await hasPermission("tabCapture"))) {
      openPermissionsPage("Grant Tab audio permission before recording");
      return;
    }
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id) throw new Error("No active tab");
    const streamId = await getTabAudioStreamId(tab.id);
    capturedAudioStream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
      video: false,
    });
    monitorAudioContext = new AudioContext();
    monitorAudioContext.createMediaStreamSource(capturedAudioStream).connect(monitorAudioContext.destination);
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const chunks = [];
    mediaRecorder = new MediaRecorder(capturedAudioStream, { mimeType });
    mediaRecorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
    mediaRecorder.addEventListener("stop", () => {
      const blob = new Blob(chunks, { type: mimeType });
      if (recordedAudioUrl) URL.revokeObjectURL(recordedAudioUrl);
      recordedAudioUrl = URL.createObjectURL(blob);
      audioPlayer.src = recordedAudioUrl;
      mediaPanel.classList.add("is-active");
      recordingState.textContent = "Recorded audio";
      capturedAudioStream?.getTracks().forEach((track) => track.stop());
      capturedAudioStream = null;
      monitorAudioContext?.close().catch(() => {});
      monitorAudioContext = null;
      setStatus("Audio ready to play or download");
    });
    mediaRecorder.start(1000);
    recordAudioButton.textContent = "Stop";
    recordingState.textContent = "Recording tab audio…";
    mediaPanel.classList.add("is-active");
    setStatus("Recording active-tab audio");
  } catch (error) {
    capturedAudioStream?.getTracks().forEach((track) => track.stop());
    capturedAudioStream = null;
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

document.getElementById("download-audio").addEventListener("click", async () => {
  if (!recordedAudioUrl) { setStatus("Record audio first"); return; }
  try {
    if (await downloadUrl(recordedAudioUrl, timestampName("tab-audio", "webm"))) setStatus("Audio download started");
  } catch (error) { setStatus(error instanceof Error ? error.message : String(error)); }
});

document.getElementById("close-media").addEventListener("click", () => {
  audioPlayer.pause();
  mediaPanel.classList.remove("is-active");
});

async function getLatestReply() {
  const requestId = crypto.randomUUID();
  await chrome.storage.session.remove("copyResult");
  await chrome.storage.session.set({ copyRequest: { id: requestId, at: Date.now() } });
  for (let attempt = 0; attempt < 40; attempt++) {
    await new Promise((resolve) => setTimeout(resolve, 150));
    const { copyResult } = await chrome.storage.session.get("copyResult");
    if (copyResult?.id !== requestId) continue;
    await chrome.storage.session.remove(["copyRequest", "copyResult"]);
    if (!copyResult.ok || !copyResult.text) {
      throw new Error(copyResult.error || "No ChatGPT response is available");
    }
    return copyResult.text;
  }
  await chrome.storage.session.remove(["copyRequest", "copyResult"]);
  throw new Error("Timed out — wait for ChatGPT to finish");
}

document.getElementById("create-wiki").addEventListener("click", async () => {
  const button = document.getElementById("create-wiki");
  button.disabled = true;
  setStatus("Reading latest response…");
  try {
    const text = await getLatestReply();
    setStatus("Creating wiki page…");
    const result = await chrome.runtime.sendMessage({ type: "CREATE_WIKI_FROM_RESPONSE", text });
    if (!result?.ok) throw new Error(result?.error || "Could not create wiki page");
    setStatus("Wiki page created");
    wikiLink.href = result.url;
    wikiLink.textContent = "Open page";
    wikiLink.hidden = false;
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  } finally {
    button.disabled = false;
  }
});

document.getElementById("copy-reply").addEventListener("click", async () => {
  setStatus("Copying latest response…");
  try {
    const text = await getLatestReply();
    try {
      await navigator.clipboard.writeText(text);
      setStatus("Latest response copied");
    } catch {
      const area = document.createElement("textarea");
      area.value = text;
      document.body.appendChild(area);
      area.select();
      const copied = document.execCommand("copy");
      area.remove();
      setStatus(copied ? "Latest response copied" : "Copy failed");
    }
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

syncJobStatusFromStorage();
chrome.runtime.sendMessage({ type: "PANEL_OPENED" }).catch(() => {});
