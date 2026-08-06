/** Populate a <select> with wiki folders (flat paths like Physics / Calculus). */

export async function fetchWikiFoldersFlat() {
  const r = await fetch("/api/wiki/folders/flat");
  if (!r.ok) {
    const raw = await r.text();
    throw new Error(raw || "Could not load folders.");
  }
  const j = await r.json();
  return j.folders || [];
}

export async function populateWikiFolderSelect(selectEl, { includeNone = true } = {}) {
  if (!selectEl) return;
  const folders = await fetchWikiFoldersFlat();
  selectEl.innerHTML = "";
  if (includeNone) {
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "— No folder —";
    selectEl.appendChild(none);
  }
  folders.forEach((f) => {
    const opt = document.createElement("option");
    opt.value = f.id;
    opt.textContent = f.label;
    selectEl.appendChild(opt);
  });
}

export function getSelectedWikiFolderId(selectEl) {
  if (!selectEl) return null;
  const v = selectEl.value.trim();
  return v || null;
}
