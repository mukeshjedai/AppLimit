const apiBaseEl = document.getElementById("apiBase");
const folderIdEl = document.getElementById("folderId");
const openEl = document.getElementById("openPageAfterCreate");
const expandEl = document.getElementById("expandAfterCreate");
const maxItemsEl = document.getElementById("expansionMaxItems");
const openIndexEl = document.getElementById("openIndexAfterExpand");
const savedEl = document.getElementById("saved");
const providerEl = document.getElementById("pagePromptProvider");
const customExtensionIdEl = document.getElementById("customExtensionId");
const customExtensionFieldsEl = document.getElementById("customExtensionFields");

function showProviderFields() {
  customExtensionFieldsEl.hidden = providerEl.value !== "custom";
}
providerEl.addEventListener("change", showProviderFields);

chrome.storage.sync.get(
  {
    apiBase: "http://localhost:3000",
    folderId: "",
    openPageAfterCreate: true,
    expandAfterCreate: true,
    expansionMaxItems: 6,
    openIndexAfterExpand: false,
    pagePromptProvider: "singularity",
    customExtensionId: "",
  },
  (data) => {
    apiBaseEl.value = data.apiBase;
    folderIdEl.value = data.folderId;
    openEl.checked = data.openPageAfterCreate;
    expandEl.checked = data.expandAfterCreate !== false;
    maxItemsEl.value = data.expansionMaxItems || 6;
    openIndexEl.checked = !!data.openIndexAfterExpand;
    providerEl.value = data.pagePromptProvider === "custom" ? "custom" : "singularity";
    customExtensionIdEl.value = data.customExtensionId || "";
    showProviderFields();
  },
);

document.getElementById("save").addEventListener("click", () => {
  const customExtensionId = customExtensionIdEl.value.trim();
  if (providerEl.value === "custom" && !/^[a-p]{32}$/.test(customExtensionId)) {
    savedEl.textContent = "Enter a valid 32-character Chrome extension ID.";
    savedEl.style.color = "#b91c1c";
    return;
  }
  chrome.storage.sync.set(
    {
      apiBase: apiBaseEl.value.trim() || "http://localhost:3000",
      folderId: folderIdEl.value.trim(),
      openPageAfterCreate: openEl.checked,
      expandAfterCreate: expandEl.checked,
      expansionMaxItems: Math.max(1, Math.min(12, parseInt(maxItemsEl.value, 10) || 6)),
      openIndexAfterExpand: openIndexEl.checked,
      pagePromptProvider: providerEl.value,
      customExtensionId,
    },
    () => {
      savedEl.style.color = "#15803d";
      savedEl.textContent = "Saved.";
      setTimeout(() => {
        savedEl.textContent = "";
      }, 2000);
    },
  );
});
