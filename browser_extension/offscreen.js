const captures = new Map();

async function startCapture(message) {
  stopCapture(message.tabId);

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: message.streamId,
      },
    },
    video: false,
  });

  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  const panner = context.createStereoPanner();
  panner.pan.value = message.pan;
  source.connect(panner).connect(context.destination);
  await context.resume();

  captures.set(message.tabId, {
    context,
    panner,
    source,
    stream,
    windowId: message.windowId,
  });

  stream.getAudioTracks()[0]?.addEventListener("ended", () => {
    stopCapture(message.tabId);
  });
}

function stopCapture(tabId) {
  const capture = captures.get(tabId);
  if (!capture) return;

  // Remove the entry first because stopping the track also emits `ended`.
  captures.delete(tabId);
  capture.stream.getTracks().forEach((track) => track.stop());
  capture.source.disconnect();
  capture.panner.disconnect();
  capture.context.close().catch(() => {});
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== "offscreen") return;

  if (message.type === "start") {
    startCapture(message)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => {
        console.error("Could not start tab audio", error);
        stopCapture(message.tabId);
        sendResponse({ ok: false, error: error.message });
      });
    return true;
  } else if (message.type === "stop") {
    stopCapture(message.tabId);
    sendResponse({ ok: true });
  } else if (message.type === "update") {
    const capture = captures.get(message.tabId);
    if (capture) {
      capture.windowId = message.windowId;
      capture.panner.pan.setTargetAtTime(message.pan, capture.context.currentTime, 0.03);
    }
    sendResponse({ ok: true });
  }
});
