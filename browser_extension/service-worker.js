importScripts("layout.js");

const OFFSCREEN_DOCUMENT = "offscreen.html";
const NATIVE_HOST = "com.thatoneguybanks.screen_sound_separation";
let creatingOffscreenDocument = null;
let nativePort = null;
let desktopState = { connected: false, enabled: false, separation: 0.75 };

function connectToDesktop() {
  if (nativePort) return;

  try {
    const port = chrome.runtime.connectNative(NATIVE_HOST);
    nativePort = port;
    port.onMessage.addListener((message) => {
      desktopState.connected = true;
      if (message.type === "state") {
        desktopState.enabled = Boolean(message.enabled);
        desktopState.separation = Math.max(0, Math.min(1, Number(message.separation) || 0));
        if (desktopState.enabled) {
          refreshCapturedTabs().catch(console.error);
        } else {
          releaseAll().catch(console.error);
        }
      } else if (message.type === "release_all") {
        releaseAll().catch(console.error);
      }
    });
    port.onDisconnect.addListener(() => {
      nativePort = null;
      desktopState = { ...desktopState, connected: false, enabled: false };
      releaseAll().catch(console.error);
    });
  } catch (error) {
    nativePort = null;
    console.debug("Desktop app is not available", error);
  }
}

function notifyDesktop(message) {
  if (!nativePort || !desktopState.connected) return;
  try {
    nativePort.postMessage(message);
  } catch (error) {
    console.debug("Could not notify desktop app", error);
  }
}

chrome.alarms.create("desktop-reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "desktop-reconnect") connectToDesktop();
});
connectToDesktop();

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
  notifyDesktop({ type: "tab_status", tabId, captured: false });
}

async function releaseAll() {
  const captures = await chrome.tabCapture.getCapturedTabs();
  const active = captures.filter((capture) => ["pending", "active"].includes(capture.status));
  await Promise.all(active.map((capture) => stopCapture(capture.tabId)));
}

chrome.action.onClicked.addListener(async (tab) => {
  if (tab.id == null || tab.windowId == null) return;

  try {
    connectToDesktop();
    if (!desktopState.connected) {
      throw new Error("Open the Screen Sound Separation desktop app first.");
    }
    if (!desktopState.enabled) {
      throw new Error("Start routing in the desktop app first.");
    }
    const captures = await chrome.tabCapture.getCapturedTabs();
    const existing = captures.find(
      (capture) => capture.tabId === tab.id && ["pending", "active"].includes(capture.status),
    );
    if (existing) {
      await stopCapture(tab.id);
      return;
    }

    await ensureOffscreenDocument();
    const position = await currentPan(tab.windowId);
    const pan = position * desktopState.separation;
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
    notifyDesktop({
      type: "tab_status",
      tabId: tab.id,
      title: tab.title || "Browser tab",
      side: position < -0.2 ? "Left" : position > 0.2 ? "Right" : "Centre",
      pan,
      captured: true,
    });
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
        const position = await currentPan(tab.windowId);
        const pan = position * desktopState.separation;
        await chrome.runtime.sendMessage({
          target: "offscreen",
          type: "update",
          tabId: capture.tabId,
          windowId: tab.windowId,
          pan,
        });
        await setManagedBadge(capture.tabId, pan);
        notifyDesktop({
          type: "tab_status",
          tabId: capture.tabId,
          title: tab.title || "Browser tab",
          side: position < -0.2 ? "Left" : position > 0.2 ? "Right" : "Centre",
          pan,
          captured: true,
        });
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
