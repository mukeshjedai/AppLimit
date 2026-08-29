/** AppLimit wiki API helpers (service worker via importScripts). */

async function getSettings() {
  return chrome.storage.sync.get({
    apiBase: "http://localhost:3000",
    folderId: "",
    openPageAfterCreate: true,
    expandAfterCreate: true,
    expansionMaxItems: 6,
    openIndexAfterExpand: false,
    pagePromptProvider: "singularity",
    customExtensionId: "",
  });
}

function wikiPageUrl(apiBase, relativePath) {
  const base = apiBase.replace(/\/$/, "");
  const path = relativePath.startsWith("/") ? relativePath : `/${relativePath}`;
  return `${base}${path}`;
}

async function saveManualWikiPage(title, body, folderId, pageId = null) {
  const settings = await getSettings();
  const base = settings.apiBase.replace(/\/$/, "");
  const res = await fetch(`${base}/api/wiki/manual/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: (title || "Untitled").slice(0, 120),
      body,
      page_id: pageId,
      folder_id: folderId || settings.folderId || null,
      auto_fallback_local: true,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Paste notes save failed (${res.status})`);
  }
  const data = await res.json();
  return {
    ...data,
    fullUrl: wikiPageUrl(settings.apiBase, data.url || `/wiki/${data.id}`),
  };
}

async function linkFromSelection(parentId, selectedText, newTitle, newBody) {
  const settings = await getSettings();
  const base = settings.apiBase.replace(/\/$/, "");
  const res = await fetch(`${base}/api/wiki/link-from-selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      parent_id: parentId,
      selected_text: selectedText,
      new_title: (newTitle || "Linked page").slice(0, 120),
      new_body: newBody,
      source: "manual",
      auto_fallback_local: true,
    }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Backlink failed (${res.status})`);
  }
  const data = await res.json();
  return {
    ...data,
    fullUrl: wikiPageUrl(settings.apiBase, data.url || `/wiki/${data.id}`),
  };
}

/** Parent holds the selection; child gets ChatGPT paste (copy button) with backlink. */
async function createSingularityWikiPage(selection, pasteBody, childTitle, folderId) {
  const trimmed = (selection || "").trim();
  if (!trimmed) throw new Error("No selection text.");
  if (!(pasteBody || "").trim()) throw new Error("ChatGPT response is empty.");

  const parentTitle =
    trimmed.split(/\n/).find((l) => l.trim())?.trim().slice(0, 100) || "Selected text";

  const parent = await saveManualWikiPage(`Source: ${parentTitle}`, trimmed, folderId);
  const child = await linkFromSelection(parent.id, trimmed, childTitle, pasteBody);
  return {
    ...child,
    parentId: parent.id,
    parentUrl: parent.fullUrl,
  };
}
