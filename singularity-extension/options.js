const apiBaseEl = document.getElementById("apiBase");
const folderIdEl = document.getElementById("folderId");
const openEl = document.getElementById("openPageAfterCreate");
const expandEl = document.getElementById("expandAfterCreate");
const maxItemsEl = document.getElementById("expansionMaxItems");
const openIndexEl = document.getElementById("openIndexAfterExpand");
const savedEl = document.getElementById("saved");

chrome.storage.sync.get(
  {
    apiBase: "http://localhost:3000",
    folderId: "",
    openPageAfterCreate: true,
    expandAfterCreate: true,
    expansionMaxItems: 6,
    openIndexAfterExpand: false,
  },
  (data) => {
    apiBaseEl.value = data.apiBase;
    folderIdEl.value = data.folderId;
    openEl.checked = data.openPageAfterCreate;
    expandEl.checked = data.expandAfterCreate !== false;
    maxItemsEl.value = data.expansionMaxItems || 6;
    openIndexEl.checked = !!data.openIndexAfterExpand;
  },
);

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set(
    {
      apiBase: apiBaseEl.value.trim() || "http://localhost:3000",
      folderId: folderIdEl.value.trim(),
      openPageAfterCreate: openEl.checked,
      expandAfterCreate: expandEl.checked,
      expansionMaxItems: Math.max(1, Math.min(12, parseInt(maxItemsEl.value, 10) || 6)),
      openIndexAfterExpand: openIndexEl.checked,
    },
    () => {
      savedEl.textContent = "Saved.";
      setTimeout(() => {
        savedEl.textContent = "";
      }, 2000);
    },
  );
});
