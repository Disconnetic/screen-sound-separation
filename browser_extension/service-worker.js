importScripts("layout.js");

const OFFSCREEN_DOCUMENT = "offscreen.html";
let creatingOffscreenDocument = null;

async function ensureOffscreenDocument() {
  const offscreenUrl = chrome.runtime.getURL(OFFSCREEN_DOCUMENT);
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [offscreenUrl],
  });
  if (contexts.length > 0) return;

  // Several browser events can arrive together; serialize document creation.
  if (!creatingOffscreenDocument) {
    creatingOffscreenDocument = chrome.offscreen.createDocument({
      url: OFFSCREEN_DOCUMENT,
      reasons: ["USER_MEDIA"],
      justification: "Replay user-enabled tab audio through a stereo panner.",
    }).finally(() => {
      creatingOffscreenDocument = null;
    });
  }
  await creatingOffscreenDocument;
}

async function currentPan(windowId) {
  const windows = await chrome.windows.getAll({ windowTypes: ["normal"] });
  return computePanForWindow(windows, windowId);
}

function badgeForPan(pan) {
  if (pan < -0.2) return { text: "L", color: "#8b5cf6" };
  if (pan > 0.2) return { text: "R", color: "#06b6d4" };
  return { text: "C", color: "#64748b" };
}

async function setManagedBadge(tabId, pan) {
  const badge = badgeForPan(pan);
  await chrome.action.setBadgeBackgroundColor({ tabId, color: badge.color });
  await chrome.action.setBadgeText({ tabId, text: badge.text });
  await chrome.action.setTitle({
    tabId,
    title: `Tab audio managed (${badge.text}). Click to release.`,
  });
}

async function clearManagedBadge(tabId) {
  await chrome.action.setBadgeText({ tabId, text: "" });
  await chrome.action.setTitle({
    tabId,
    title: "Toggle audio separation for this tab",
  });
}

async function stopCapture(tabId) {
  await chrome.runtime.sendMessage({ target: "offscreen", type: "stop", tabId });
  await clearManagedBadge(tabId);
}

chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id == null || tab.windowId == null) return;

  try {
    const captures = await chrome.tabCapture.getCapturedTabs();
    const existing = captures.find(
      (capture) => capture.tabId === tab.id && ["pending", "active"].includes(capture.status),
    );
    if (existing) {
      await stopCapture(tab.id);
      return;
    }

    await ensureOffscreenDocument();
    const pan = await currentPan(tab.windowId);
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
    const result = await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "start",
      tabId: tab.id,
      windowId: tab.windowId,
      streamId,
      pan,
    });
    if (!result?.ok) {
      throw new Error(result?.error || "The tab audio graph did not start.");
    }
    await setManagedBadge(tab.id, pan);
  } catch (error) {
    console.error("Could not toggle tab capture", error);
    await chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: "#e11d48" });
    await chrome.action.setBadgeText({ tabId: tab.id, text: "!" });
    await chrome.action.setTitle({ tabId: tab.id, title: `Tab audio error: ${error.message}` });
  }
});

async function refreshCapturedTabs() {
  const captures = await chrome.tabCapture.getCapturedTabs();
  const active = captures.filter((capture) => ["pending", "active"].includes(capture.status));
  await Promise.all(
    active.map(async (capture) => {
      try {
        const tab = await chrome.tabs.get(capture.tabId);
        const pan = await currentPan(tab.windowId);
        await chrome.runtime.sendMessage({
          target: "offscreen",
          type: "update",
          tabId: capture.tabId,
          windowId: tab.windowId,
          pan,
        });
        await setManagedBadge(capture.tabId, pan);
      } catch (error) {
        console.warn("Could not refresh a captured tab", capture.tabId, error);
      }
    }),
  );
}

chrome.windows.onBoundsChanged.addListener(() => {
  refreshCapturedTabs().catch((error) => console.error("Window refresh failed", error));
});

chrome.tabs.onAttached.addListener(() => {
  refreshCapturedTabs().catch((error) => console.error("Tab move refresh failed", error));
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.runtime.sendMessage({ target: "offscreen", type: "stop", tabId }).catch(() => {});
});
