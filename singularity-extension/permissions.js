const statusEl = document.getElementById("status");
const downloadsButton = document.getElementById("grant-downloads");
const tabAudioButton = document.getElementById("grant-tab-audio");

async function refresh() {
  const downloads = await chrome.permissions.contains({ permissions: ["downloads"] });
  const tabCapture = await chrome.permissions.contains({ permissions: ["tabCapture"] });
  downloadsButton.textContent = downloads ? "Granted" : "Grant";
  downloadsButton.classList.toggle("granted", downloads);
  tabAudioButton.textContent = tabCapture ? "Granted" : "Grant";
  tabAudioButton.classList.toggle("granted", tabCapture);
}

async function request(permission, label) {
  try {
    const granted = await chrome.permissions.request({ permissions: [permission] });
    statusEl.textContent = granted ? `${label} permission granted.` : `${label} permission was not granted.`;
  } catch (error) {
    statusEl.textContent = error instanceof Error ? error.message : String(error);
  }
  await refresh();
}

downloadsButton.addEventListener("click", () => request("downloads", "Downloads"));
tabAudioButton.addEventListener("click", () => request("tabCapture", "Tab audio"));
refresh();
