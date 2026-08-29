/** Bridge user-initiated wiki actions into the Singularity service worker. */
(function () {
  function deepText(element) {
    if (!element) return "";
    const shadowText = element.shadowRoot ? element.shadowRoot.textContent : "";
    const childShadowText = [...element.querySelectorAll("*")]
      .map((child) => child.shadowRoot?.textContent || "")
      .join("\n");
    return [element.textContent || "", shadowText, childShadowText].filter(Boolean).join("\n");
  }

  document.addEventListener("singularity:start-page-test", (event) => {
    const detail = event.detail || {};
    const renderedContent = deepText(document.querySelector("[data-wiki-test-content]"));
    const content = String(detail.content || renderedContent || "").slice(0, 250000);
    chrome.runtime.sendMessage({
      type: "START_PAGE_TEST",
      title: String(detail.title || document.title).slice(0, 240),
      content,
      pageUrl: String(detail.pageUrl || location.href),
    }).then((result) => {
      document.dispatchEvent(new CustomEvent("singularity:start-page-test-result", { detail: result || { ok: true } }));
    }).catch((error) => {
      document.dispatchEvent(new CustomEvent("singularity:start-page-test-result", {
        detail: { ok: false, error: error instanceof Error ? error.message : String(error) },
      }));
    });
  });
})();
