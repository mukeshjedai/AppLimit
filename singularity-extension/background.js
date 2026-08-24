const MENU_SIDEBAR = "sidebar-open";
const MENU_SEND_TEXT = "send-selection";
const MENU_LIST_PROBLEMS = "list-problems";
const MENU_SEND_SHOT = "send-screenshot";

importScripts("wiki-api.js", "expansion.js");

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function notifySidePanel(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {});
}

async function updateJobProgress(label, phase, extra = {}) {
  const { jobStatus } = await chrome.storage.session.get("jobStatus");
  const jobStartedAt = jobStatus?.jobStartedAt || Date.now();
  const log = [...(jobStatus?.log || []), label];
  if (log.length > 40) log.splice(0, log.length - 40);
  const next = {
    phase,
    label,
    jobStartedAt,
    log,
    updatedAt: Date.now(),
    ...extra,
  };
  await chrome.storage.session.set({ jobStatus: next });
  notifySidePanel({ type: "JOB_PROGRESS", label, phase, log, ...extra });
}

function registerContextMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_SIDEBAR,
      title: "Open Singularity",
      contexts: ["all"],
    });
    chrome.contextMenus.create({
      id: MENU_SEND_TEXT,
      title: "Send to Singularity",
      contexts: ["selection"],
    });
    chrome.contextMenus.create({
      id: MENU_LIST_PROBLEMS,
      title: "List problems",
      contexts: ["selection"],
    });
    chrome.contextMenus.create({
      id: MENU_SEND_SHOT,
      title: "Send screenshot to Singularity",
      contexts: ["page", "frame", "image", "video", "link"],
    });
  });
}

function buildPrompt(selection, mode) {
  const text = (selection || "").trim();
  if (mode === "problems") {
    return (
      "From the following content, extract and list every problem, exercise, or question. " +
      "Return a numbered markdown list. For each item include the problem statement and any key details.\n\n" +
      "---\n" +
      text +
      "\n---"
    );
  }
  return (
    "Read the following selected content and provide a clear, structured answer or explanation. " +
    "Use markdown with headings and lists where helpful.\n\n" +
    "---\n" +
    text +
    "\n---"
  );
}

function buildTitle(selection, mode) {
  if (mode === "problems") {
    const d = new Date().toISOString().slice(0, 10);
    return `Problem list (${d})`;
  }
  const line = (selection || "")
    .trim()
    .split(/\n/)
    .find((l) => l.trim()) || "Selection notes";
  return line.trim().slice(0, 100);
}

function configureSidePanel() {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  chrome.sidePanel.setOptions({ path: "sidepanel.html", enabled: true }).catch(() => {});
}

/** Cached tab ids — SO workaround when async queries would break the user gesture. */
let activeTabId;
let activeWindowId;

chrome.tabs.onActivated.addListener((info) => {
  activeTabId = info.tabId;
  chrome.tabs.get(info.tabId, (t) => {
    if (t?.windowId != null) activeWindowId = t.windowId;
  });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (tab.active && tab.windowId != null) {
    activeTabId = tabId;
    activeWindowId = tab.windowId;
  }
});

/**
 * Open side panel during a user gesture.
 * SO: https://stackoverflow.com/questions/77213045
 * — no await before open(); setOptions is preconfigured on install.
 */
function openSidePanelFromGesture(tab) {
  const windowId = tab?.windowId ?? activeWindowId;
  const tabId = tab?.id ?? activeTabId;
  const onFail = (e) => {
    console.warn("sidePanel.open failed:", e);
    promptOpenPanel("Click the Singularity toolbar icon…");
  };
  if (windowId != null) {
    chrome.sidePanel.open({ windowId }).catch(onFail);
  } else if (tabId != null) {
    chrome.sidePanel.open({ tabId }).catch(onFail);
  }
}

function promptOpenPanel(label) {
  chrome.action.setBadgeText({ text: "●" });
  chrome.action.setBadgeBackgroundColor({ color: "#7c3aed" });
  notifySidePanel({ type: "JOB_PROGRESS", label: label || "Click the Singularity toolbar icon…" });
}

function clearPanelPrompt() {
  chrome.action.setBadgeText({ text: "" });
}

async function waitForPromptResult(jobStartedAt, timeoutMs = 240000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const { promptResult } = await chrome.storage.session.get("promptResult");
    if (
      promptResult &&
      promptResult.jobStartedAt === jobStartedAt &&
      promptResult.done
    ) {
      await chrome.storage.session.remove("promptResult");
      return promptResult;
    }
    await sleep(400);
  }
  return { ok: false, error: "Timed out waiting for ChatGPT in the side panel." };
}

async function chatGPTQuery(prompt, label, progressExtra = {}) {
  const { jobStatus } = await chrome.storage.session.get("jobStatus");
  const jobStartedAt = jobStatus?.jobStartedAt || Date.now();
  await updateJobProgress(label, "chatgpt", { ...progressExtra, jobStartedAt });
  await chrome.storage.session.remove("promptResult");
  await chrome.storage.session.set({
    pendingJob: {
      prompt,
      selection: "",
      mode: "expansion",
      title: "",
      jobStartedAt,
    },
  });
  notifySidePanel({ type: "FOCUS_PANEL_FRAME" });
  const result = await waitForPromptResult(jobStartedAt);
  if (!result.ok || !result.text) {
    throw new Error(result.error || "ChatGPT query failed.");
  }
  await sleep(1200);
  return result.text;
}

async function runExpansionPipeline(rootTitle, answerBody, rootPagePath, folderId) {
  const settings = await getSettings();
  if (settings.expandAfterCreate === false) return null;

  const maxItems = Math.max(1, Math.min(12, settings.expansionMaxItems || 6));
  let step = 0;

  const listsRaw = await chatGPTQuery(
    buildExtractListsPrompt(answerBody),
    "Step 1 — Extracting terms, concepts, problems…",
    { expansionStep: ++step, expansionPhase: "extract" },
  );
  const lists = parseExtractedLists(listsRaw);
  const terms = lists.terms.slice(0, maxItems);
  const concepts = lists.concepts.slice(0, maxItems);
  const problems = lists.problems.slice(0, maxItems);
  const totalSteps =
    1 + terms.length + concepts.length + (problems.length ? 1 : 0) + 1;

  await updateJobProgress(
    `Found ${terms.length} terms, ${concepts.length} concepts, ${problems.length} problems`,
    "expansion",
    { expansionStep: step, expansionTotal: totalSteps, expansionPhase: "plan" },
  );

  const created = { terms: [], concepts: [], problemsPage: null };

  for (let i = 0; i < terms.length; i++) {
    const term = terms[i];
    const stepLabel = `Step ${step + 1}/${totalSteps} — Term ${i + 1}/${terms.length}: ${term.slice(0, 32)}`;
    step += 1;
    const body = ensureStructuredFormat(
      await chatGPTQuery(buildTermPrompt(term, answerBody), `${stepLabel} (ChatGPT…)`, {
        expansionStep: step,
        expansionTotal: totalSteps,
        expansionPhase: "term",
      }),
    );
    await updateJobProgress(`${stepLabel} — saving wiki page…`, "expansion", {
      expansionStep: step,
      expansionTotal: totalSteps,
    });
    const page = await saveManualWikiPage(`Term: ${term}`.slice(0, 120), body, folderId);
    created.terms.push({ label: term, id: page.id, path: page.url, url: page.fullUrl });
  }

  for (let i = 0; i < concepts.length; i++) {
    const concept = concepts[i];
    const stepLabel = `Step ${step + 1}/${totalSteps} — Concept ${i + 1}/${concepts.length}: ${concept.slice(0, 30)}`;
    step += 1;
    const body = ensureStructuredFormat(
      await chatGPTQuery(buildConceptPrompt(concept, answerBody), `${stepLabel} (ChatGPT…)`, {
        expansionStep: step,
        expansionTotal: totalSteps,
        expansionPhase: "concept",
      }),
    );
    await updateJobProgress(`${stepLabel} — saving wiki page…`, "expansion", {
      expansionStep: step,
      expansionTotal: totalSteps,
    });
    const page = await saveManualWikiPage(`Concept: ${concept}`.slice(0, 120), body, folderId);
    created.concepts.push({ label: concept, id: page.id, path: page.url, url: page.fullUrl });
  }

  if (problems.length) {
    step += 1;
    const stepLabel = `Step ${step}/${totalSteps} — Problem list (${problems.length} items)`;
    const body = ensureStructuredFormat(
      await chatGPTQuery(buildProblemsPrompt(problems, answerBody), `${stepLabel} (ChatGPT…)`, {
        expansionStep: step,
        expansionTotal: totalSteps,
        expansionPhase: "problems",
      }),
    );
    await updateJobProgress(`${stepLabel} — saving wiki page…`, "expansion", {
      expansionStep: step,
      expansionTotal: totalSteps,
    });
    const page = await saveManualWikiPage(
      `Problems: ${rootTitle}`.slice(0, 120),
      body,
      folderId,
    );
    created.problemsPage = { id: page.id, path: page.url, url: page.fullUrl };
  }

  step += 1;
  await updateJobProgress(
    `Step ${step}/${totalSteps} — Creating index page…`,
    "expansion",
    { expansionStep: step, expansionTotal: totalSteps, expansionPhase: "index" },
  );
  const indexBody = buildIndexMarkdown(rootTitle, rootPagePath, created, {
    terms,
    concepts,
    problems,
  });
  const indexPage = await saveManualWikiPage(
    `Index: ${rootTitle}`.slice(0, 120),
    indexBody,
    folderId,
  );

  const total =
    created.terms.length + created.concepts.length + (created.problemsPage ? 1 : 0) + 1;

  return {
    indexUrl: indexPage.fullUrl,
    indexPath: indexPage.url,
    pageCount: total,
    terms: created.terms.length,
    concepts: created.concepts.length,
    hasProblems: !!created.problemsPage,
  };
}

async function attachScreenshotToPanel(dataUrl) {
  await chrome.storage.session.set({
    pendingScreenshot: dataUrl,
    pendingScreenshotAt: Date.now(),
  });
  for (let i = 0; i < 36; i++) {
    const { screenshotResult } = await chrome.storage.session.get("screenshotResult");
    if (screenshotResult?.at && Date.now() - screenshotResult.at < 5000) {
      await chrome.storage.session.remove(["pendingScreenshot", "pendingScreenshotAt", "screenshotResult"]);
      notifySidePanel({ type: "ATTACH_DONE", ok: screenshotResult.ok });
      return screenshotResult.ok;
    }
    await sleep(500);
  }
  notifySidePanel({ type: "ATTACH_DONE", ok: false });
  return false;
}

async function runTextJob(tab, selection, mode) {
  const trimmed = (selection || "").trim();
  if (!trimmed) {
    notifySidePanel({ type: "JOB_FAILED", error: "No text selected." });
    return;
  }

  const jobStartedAt = Date.now();
  const prompt = buildPrompt(trimmed, mode);
  const title = buildTitle(trimmed, mode);
  const label = mode === "problems" ? "Listing problems…" : "Asking ChatGPT…";

  await chrome.storage.session.set({
    pendingJob: {
      prompt,
      selection: trimmed,
      mode,
      title,
      jobStartedAt,
    },
    jobStatus: {
      phase: "starting",
      label,
      jobStartedAt,
      log: [label],
    },
  });
  await chrome.storage.session.remove("promptResult");

  notifySidePanel({ type: "JOB_STARTED", mode, label });
  notifySidePanel({ type: "FOCUS_PANEL_FRAME" });

  const result = await waitForPromptResult(jobStartedAt);
  clearPanelPrompt();

  if (!result.ok || !result.text) {
    await chrome.storage.session.set({
      jobStatus: {
        phase: "failed",
        label: result.error || "No response from ChatGPT.",
        jobStartedAt,
      },
    });
    notifySidePanel({
      type: "JOB_FAILED",
      error: result.error || "No response from ChatGPT.",
    });
    return;
  }

  await updateJobProgress("Saving paste notes & backlink…", "wiki", { jobStartedAt });

  try {
    const settings = await getSettings();
    const page = await createSingularityWikiPage(
      trimmed,
      result.text,
      title,
      settings.folderId,
    );
    await updateJobProgress("Answer page saved", "done", {
      jobStartedAt,
      url: page.fullUrl,
      parentUrl: page.parentUrl,
    });
    notifySidePanel({
      type: "WIKI_CREATED",
      url: page.fullUrl,
      parentUrl: page.parentUrl,
      title,
      expanding: mode === "explain" && settings.expandAfterCreate !== false,
    });
    if (settings.openPageAfterCreate && page.fullUrl) {
      chrome.tabs.create({ url: page.fullUrl });
    }

    if (mode === "explain" && settings.expandAfterCreate !== false) {
      try {
        await updateJobProgress("Starting expansion (terms → concepts → problems)…", "expansion", {
          jobStartedAt,
          expansionStep: 0,
        });
        const expansion = await runExpansionPipeline(
          title,
          result.text,
          page.url || `/wiki/${page.id}`,
          settings.folderId,
        );
        if (expansion) {
          const doneLabel = `Done — ${expansion.pageCount} pages (${expansion.terms} terms, ${expansion.concepts} concepts${expansion.hasProblems ? ", problems" : ""})`;
          await updateJobProgress(doneLabel, "done", {
            jobStartedAt,
            url: expansion.indexUrl,
            expansionStep: expansion.pageCount,
            expansionTotal: expansion.pageCount,
          });
          notifySidePanel({
            type: "EXPANSION_DONE",
            indexUrl: expansion.indexUrl,
            pageCount: expansion.pageCount,
          });
          if (settings.openIndexAfterExpand && expansion.indexUrl) {
            chrome.tabs.create({ url: expansion.indexUrl });
          }
        }
      } catch (expErr) {
        const msg = expErr instanceof Error ? expErr.message : String(expErr);
        await updateJobProgress(`Answer saved; expansion failed: ${msg}`, "failed", { jobStartedAt });
        notifySidePanel({ type: "JOB_FAILED", error: `Expansion failed: ${msg}` });
      }
    }
  } catch (e) {
    const err = e instanceof Error ? e.message : String(e);
    await chrome.storage.session.set({
      jobStatus: { phase: "failed", label: err, jobStartedAt },
    });
    notifySidePanel({ type: "JOB_FAILED", error: err });
  }
}

async function captureAndSend(tab) {
  if (!tab?.windowId) return;

  const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
    format: "png",
    quality: 92,
  });

  notifySidePanel({ type: "ATTACH_SCREENSHOT" });
  await attachScreenshotToPanel(dataUrl);
  clearPanelPrompt();
}

registerContextMenus();
configureSidePanel();
chrome.runtime.onInstalled.addListener(() => {
  registerContextMenus();
  configureSidePanel();
});
chrome.runtime.onStartup.addListener(() => {
  registerContextMenus();
  configureSidePanel();
});

function runTextJobFromMenu(tab, selection, mode) {
  const trimmed = (selection || "").trim();
  if (!trimmed) {
    notifySidePanel({ type: "JOB_FAILED", error: "No text selected." });
    return;
  }
  runTextJob(tab, trimmed, mode).catch((e) => {
    console.error(e);
    notifySidePanel({ type: "JOB_FAILED", error: String(e) });
  });
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (!tab) return;
  if (info.menuItemId === MENU_SIDEBAR) {
    openSidePanelFromGesture(tab);
    return;
  }
  if (info.menuItemId === MENU_SEND_TEXT) {
    openSidePanelFromGesture(tab);
    runTextJobFromMenu(tab, info.selectionText || "", "explain");
    return;
  }
  if (info.menuItemId === MENU_LIST_PROBLEMS) {
    openSidePanelFromGesture(tab);
    runTextJobFromMenu(tab, info.selectionText || "", "problems");
    return;
  }
  if (info.menuItemId === MENU_SEND_SHOT) {
    openSidePanelFromGesture(tab);
    captureAndSend(tab).catch(console.error);
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "CREATE_CHAT_ANCHOR") {
    // Keep open() in the synchronous message handler so Chrome retains the click gesture.
    openSidePanelFromGesture(_sender.tab);
    const job = {
      pageId: String(msg.pageId || ""),
      selection: String(msg.selection || "").trim(),
      pageUrl: String(msg.pageUrl || ""),
      startedAt: Date.now(),
    };
    if (!job.pageId || !job.selection) {
      sendResponse({ ok: false, error: "A wiki page and selected text are required." });
      return false;
    }
    chrome.storage.session.set({ pendingChatAnchor: job }).then(() => {
      notifySidePanel({ type: "START_CHAT_ANCHOR" });
      updateJobProgress("Creating Singularity chat anchor…", "chatgpt", {
        jobStartedAt: job.startedAt,
      });
      sendResponse({ ok: true });
    }).catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }
  if (msg.type === "CHAT_ANCHOR_READY") {
    chrome.storage.session.get("pendingChatAnchor").then(async ({ pendingChatAnchor }) => {
      if (!pendingChatAnchor || pendingChatAnchor.startedAt !== msg.startedAt) {
        sendResponse({ ok: false, error: "Chat anchor job expired." });
        return;
      }
      try {
        await updateJobProgress("Saving superscript chat anchor…", "wiki", {
          jobStartedAt: pendingChatAnchor.startedAt,
        });
        await saveChatAnchor(
          pendingChatAnchor.pageId,
          pendingChatAnchor.selection,
          String(msg.chatUrl || ""),
        );
        await chrome.storage.session.remove("pendingChatAnchor");
        await updateJobProgress("Singularity chat anchor saved", "done", {
          jobStartedAt: pendingChatAnchor.startedAt,
          url: pendingChatAnchor.pageUrl,
        });
        if (_sender.tab?.id != null) {
          chrome.tabs.sendMessage(_sender.tab.id, { type: "CHAT_ANCHOR_SAVED" }).catch(() => {});
        }
        // The sender is ChatGPT's frame; notify the original wiki tab by URL as well.
        const tabs = await chrome.tabs.query({});
        for (const tab of tabs) {
          if (tab.id != null && tab.url === pendingChatAnchor.pageUrl) {
            chrome.tabs.sendMessage(tab.id, { type: "CHAT_ANCHOR_SAVED" }).catch(() => {});
          }
        }
        sendResponse({ ok: true });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        notifySidePanel({ type: "JOB_FAILED", error: message });
        const tabs = await chrome.tabs.query({});
        for (const tab of tabs) {
          if (tab.id != null && tab.url === pendingChatAnchor.pageUrl) {
            chrome.tabs.sendMessage(tab.id, { type: "CHAT_ANCHOR_FAILED", error: message }).catch(() => {});
          }
        }
        sendResponse({ ok: false, error: message });
      }
    });
    return true;
  }
  if (msg.type === "OPEN_SIDE_PANEL") {
    const tabId = _sender.tab?.id ?? activeTabId;
    const windowId = _sender.tab?.windowId ?? activeWindowId;
    const p =
      windowId != null
        ? chrome.sidePanel.open({ windowId, tabId })
        : tabId != null
          ? chrome.sidePanel.open({ tabId })
          : Promise.reject(new Error("No tab"));
    p.then(() => sendResponse({ ok: true })).catch((e) =>
      sendResponse({ ok: false, error: String(e) }),
    );
    return true;
  }
  if (msg.type === "FOCUS_PANEL_FRAME") {
    notifySidePanel({ type: "FOCUS_PANEL_FRAME" });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "CHATGPT_ACTIVITY") {
    notifySidePanel({
      type: "CHATGPT_ACTIVITY",
      activity: msg.activity,
      detail: msg.detail || "",
    });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "PANEL_READY") {
    clearPanelPrompt();
    notifySidePanel({ type: "CHATGPT_READY" });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "PANEL_OPENED") {
    clearPanelPrompt();
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "PROMPT_RESULT") {
    chrome.storage.session.set({
      promptResult: {
        ok: !!msg.ok,
        text: msg.text || "",
        error: msg.error || "",
        jobStartedAt: msg.jobStartedAt,
        done: true,
      },
    });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "SCREENSHOT_RESULT") {
    chrome.storage.session.set({
      screenshotResult: { ok: !!msg.ok, at: Date.now() },
    });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "SESSION_GET") {
    chrome.storage.session.get(msg.keys).then(sendResponse);
    return true;
  }
  if (msg.type === "SESSION_SET") {
    chrome.storage.session.set(msg.data).then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type === "SESSION_REMOVE") {
    chrome.storage.session.remove(msg.keys).then(() => sendResponse({ ok: true }));
    return true;
  }
  if (msg.type === "FLUSH_PENDING_SCREENSHOT") {
    chrome.storage.session.get(["pendingScreenshot"]).then((data) => {
      if (!data.pendingScreenshot) {
        sendResponse({ ok: false });
        return;
      }
      attachScreenshotToPanel(data.pendingScreenshot).then((ok) => sendResponse({ ok }));
    });
    return true;
  }
});
