const STORAGE_KEY = "wiki-sidebar-expanded-v1";

const treeEl = document.getElementById("wiki-sidebar-tree");
const emptyEl = document.getElementById("wiki-sidebar-empty");
const errEl = document.getElementById("wiki-sidebar-err");

const fileModal = document.getElementById("wiki-sidebar-file-modal");
const fileNameInput = document.getElementById("wiki-sidebar-file-name");
const fileTypeSelect = document.getElementById("wiki-sidebar-file-type");
const fileErrEl = document.getElementById("wiki-sidebar-file-err");

const folderModal = document.getElementById("wiki-sidebar-folder-modal");
const folderNameInput = document.getElementById("wiki-sidebar-folder-name");
const folderErrEl = document.getElementById("wiki-sidebar-folder-err");
const folderTitleEl = document.getElementById("wiki-sidebar-folder-title");

let tree = [];
let expanded = loadExpanded();
let pendingFileFolderId = null;
let pendingFolderParentId = null;

function loadExpanded() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return new Set(JSON.parse(raw));
  } catch {
    /* ignore */
  }
  return new Set();
}

function saveExpanded() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...expanded]));
}

function showErr(msg) {
  if (!errEl) return;
  if (msg) {
    errEl.textContent = msg;
    errEl.hidden = false;
  } else {
    errEl.textContent = "";
    errEl.hidden = true;
  }
}

function openModal(modal) {
  if (!modal) return;
  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function closeModal(modal) {
  if (!modal) return;
  modal.classList.remove("is-open");
  modal.setAttribute("aria-hidden", "true");
}

function linkHref(link) {
  const url = (link.url || "").trim();
  if (url) return url;
  if (link.wiki_page_id) return `/wiki/${link.wiki_page_id}`;
  return "#";
}

function isLinkActive(link) {
  const href = linkHref(link);
  if (!href || href === "#") return false;
  const path = window.location.pathname;
  const search = window.location.search;
  if (href.startsWith("/wiki/") && path === href) return true;
  if (path === href) return true;
  const editMatch = search.match(/[?&]edit=([^&]+)/);
  if (editMatch && link.wiki_page_id === editMatch[1]) return true;
  if (link.wiki_page_id && path === `/wiki/${link.wiki_page_id}`) return true;
  return false;
}

function ensureDefaultExpanded(nodes) {
  if (expanded.size) return;
  (nodes || []).forEach((n) => expanded.add(n.id));
  saveExpanded();
}

function toggleFolder(folderId) {
  if (expanded.has(folderId)) expanded.delete(folderId);
  else expanded.add(folderId);
  saveExpanded();
  renderTree();
}

function renderFolder(node) {
  const children = node.children || [];
  const links = node.links || [];
  const hasContent = children.length > 0 || links.length > 0;
  const isOpen = expanded.has(node.id);

  const li = document.createElement("li");
  li.className = "wiki-sidebar__folder";
  li.setAttribute("role", "treeitem");
  li.setAttribute("aria-expanded", isOpen ? "true" : "false");

  const row = document.createElement("div");
  row.className = "wiki-sidebar__folder-row";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "wiki-sidebar__toggle" + (hasContent ? "" : " is-empty");
  toggle.textContent = isOpen ? "▼" : "▶";
  toggle.title = isOpen ? "Collapse folder" : "Expand folder";
  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleFolder(node.id);
  });

  const nameBtn = document.createElement("button");
  nameBtn.type = "button";
  nameBtn.className = "wiki-sidebar__folder-name";
  nameBtn.textContent = node.name || "Folder";
  nameBtn.title = node.name || "Folder";
  nameBtn.addEventListener("click", () => toggleFolder(node.id));

  const addFileBtn = document.createElement("button");
  addFileBtn.type = "button";
  addFileBtn.className = "wiki-sidebar__icon-btn";
  addFileBtn.textContent = "+";
  addFileBtn.title = "New file in this folder";
  addFileBtn.setAttribute("aria-label", "New file in this folder");
  addFileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    openFileModal(node.id);
  });

  const addSubfolderBtn = document.createElement("button");
  addSubfolderBtn.type = "button";
  addSubfolderBtn.className = "wiki-sidebar__icon-btn wiki-sidebar__icon-btn--subtle";
  addSubfolderBtn.textContent = "📁";
  addSubfolderBtn.title = "New subfolder";
  addSubfolderBtn.setAttribute("aria-label", "New subfolder");
  addSubfolderBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    openFolderModal(node.id);
  });

  row.appendChild(toggle);
  row.appendChild(nameBtn);
  row.appendChild(addSubfolderBtn);
  row.appendChild(addFileBtn);
  li.appendChild(row);

  const body = document.createElement("div");
  body.className = "wiki-sidebar__folder-body";
  if (!isOpen) body.hidden = true;

  links.forEach((link) => {
    const a = document.createElement("a");
    a.className = "wiki-sidebar__file";
    a.href = linkHref(link);
    a.textContent = link.title || "Untitled";
    a.title = link.title || "Untitled";
    if (isLinkActive(link)) a.classList.add("is-active");
    body.appendChild(a);
  });

  if (children.length) {
    const sub = document.createElement("ul");
    sub.setAttribute("role", "group");
    children.forEach((child) => sub.appendChild(renderFolder(child)));
    body.appendChild(sub);
  }

  li.appendChild(body);
  return li;
}

function renderTree() {
  if (!treeEl) return;
  treeEl.innerHTML = "";
  ensureDefaultExpanded(tree);

  if (!tree.length) {
    if (emptyEl) emptyEl.hidden = false;
    return;
  }
  if (emptyEl) emptyEl.hidden = true;

  tree.forEach((node) => treeEl.appendChild(renderFolder(node)));
}

async function refreshTree() {
  showErr("");
  try {
    const res = await fetch("/api/wiki/folders/tree");
    if (!res.ok) throw new Error("Could not load folders.");
    const data = await res.json();
    tree = data.tree || [];
    if (data.warning) showErr(data.warning);
    renderTree();
  } catch (e) {
    showErr(e.message || "Could not load folders.");
    tree = [];
    renderTree();
  }
}

function openFileModal(folderId) {
  pendingFileFolderId = folderId;
  fileErrEl.textContent = "";
  fileNameInput.value = "";
  fileTypeSelect.value = "post_notes";
  openModal(fileModal);
  setTimeout(() => fileNameInput.focus(), 0);
}

function openFolderModal(parentId = null) {
  pendingFolderParentId = parentId;
  folderErrEl.textContent = "";
  folderNameInput.value = "";
  folderTitleEl.textContent = parentId ? "New subfolder" : "New folder";
  openModal(folderModal);
  setTimeout(() => folderNameInput.focus(), 0);
}

async function createFile() {
  const title = fileNameInput.value.trim();
  if (!title) {
    fileErrEl.textContent = "File name is required.";
    return;
  }
  fileErrEl.textContent = "";
  const folderId = pendingFileFolderId;
  if (!folderId) return;

  try {
    const res = await fetch("/api/wiki/folders/files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        folder_id: folderId,
        title,
        page_type: fileTypeSelect.value,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Could not create file.");
    closeModal(fileModal);
    expanded.add(folderId);
    saveExpanded();
    await refreshTree();
    if (data.edit_url) window.location.href = data.edit_url;
  } catch (e) {
    fileErrEl.textContent = e.message || "Could not create file.";
  }
}

async function createFolder() {
  const name = folderNameInput.value.trim();
  if (!name) {
    folderErrEl.textContent = "Folder name is required.";
    return;
  }
  folderErrEl.textContent = "";

  try {
    const body = { name };
    if (pendingFolderParentId) body.parent_id = pendingFolderParentId;
    const res = await fetch("/api/wiki/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Could not create folder.");
    closeModal(folderModal);
    const folder = data.folder;
    if (folder?.id) {
      expanded.add(folder.id);
      if (pendingFolderParentId) expanded.add(pendingFolderParentId);
      saveExpanded();
    }
    await refreshTree();
  } catch (e) {
    folderErrEl.textContent = e.message || "Could not create folder.";
  }
}

document.getElementById("wiki-sidebar-new-folder")?.addEventListener("click", () => {
  openFolderModal(null);
});

document.getElementById("wiki-sidebar-file-cancel")?.addEventListener("click", () => {
  closeModal(fileModal);
});
document.getElementById("wiki-sidebar-file-go")?.addEventListener("click", createFile);
fileNameInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") createFile();
});

document.getElementById("wiki-sidebar-folder-cancel")?.addEventListener("click", () => {
  closeModal(folderModal);
});
document.getElementById("wiki-sidebar-folder-go")?.addEventListener("click", createFolder);
folderNameInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") createFolder();
});

[fileModal, folderModal].forEach((modal) => {
  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeModal(modal);
  });
});

refreshTree();
