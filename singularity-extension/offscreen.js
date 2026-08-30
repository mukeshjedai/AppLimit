chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "OFFSCREEN_CAPTURE_FRAME") return false;

  (async () => {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          mandatory: {
            chromeMediaSource: "desktop",
            chromeMediaSourceId: message.streamId,
          },
        },
      });
      const video = document.createElement("video");
      video.srcObject = stream;
      video.muted = true;
      await video.play();
      if (!video.videoWidth || !video.videoHeight) {
        await new Promise((resolve) => video.addEventListener("loadedmetadata", resolve, { once: true }));
      }
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Canvas is unavailable.");
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      sendResponse({ ok: true, dataUrl: canvas.toDataURL("image/png") });
    } catch (error) {
      sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) });
    } finally {
      stream?.getTracks().forEach((track) => track.stop());
    }
  })();
  return true;
});
