/**
 * Calculate a stereo pan value from the horizontal positions of Chrome windows.
 * The leftmost window is -1, the rightmost is +1, and a lone window is centred.
 *
 * The desktop app will eventually provide monitor-aware positions. Window centres
 * are sufficient for this isolated proof of concept when one window is placed on
 * each display.
 */
function computePanForWindow(windows, targetWindowId) {
  const usable = windows
    .filter((window) => window.state !== "minimized")
    .filter((window) => Number.isFinite(window.left) && Number.isFinite(window.width))
    .map((window) => ({
      id: window.id,
      center: window.left + window.width / 2,
    }));

  const target = usable.find((window) => window.id === targetWindowId);
  if (!target || usable.length < 2) return 0;

  const centers = usable.map((window) => window.center);
  const left = Math.min(...centers);
  const right = Math.max(...centers);
  if (right <= left) return 0;

  return Math.max(-1, Math.min(1, ((target.center - left) / (right - left)) * 2 - 1));
}

/** Map a Chrome window to the physical display containing most of it. */
function computePanForDisplay(displays, targetWindow) {
  const usable = displays
    .filter((display) => display.activeState !== "inactive")
    .filter((display) => display.bounds)
    .map((display) => ({
      id: display.id,
      left: display.bounds.left,
      top: display.bounds.top,
      right: display.bounds.left + display.bounds.width,
      bottom: display.bounds.top + display.bounds.height,
      center: display.bounds.left + display.bounds.width / 2,
    }));
  if (!targetWindow || usable.length < 2) return 0;

  const windowRect = {
    left: targetWindow.left,
    top: targetWindow.top,
    right: targetWindow.left + targetWindow.width,
    bottom: targetWindow.top + targetWindow.height,
    center: targetWindow.left + targetWindow.width / 2,
  };
  const overlap = (display) =>
    Math.max(0, Math.min(windowRect.right, display.right) - Math.max(windowRect.left, display.left)) *
    Math.max(0, Math.min(windowRect.bottom, display.bottom) - Math.max(windowRect.top, display.top));

  const selected = usable.reduce((best, display) => {
    const area = overlap(display);
    const distance = Math.abs(windowRect.center - display.center);
    if (!best || area > best.area || (area === best.area && distance < best.distance)) {
      return { display, area, distance };
    }
    return best;
  }, null)?.display;
  if (!selected) return 0;

  const left = Math.min(...usable.map((display) => display.center));
  const right = Math.max(...usable.map((display) => display.center));
  if (right <= left) return 0;
  return Math.max(-1, Math.min(1, ((selected.center - left) / (right - left)) * 2 - 1));
}

// Keep the calculation testable with Node without changing how Chrome loads it.
if (typeof module !== "undefined") {
  module.exports = { computePanForDisplay, computePanForWindow };
}
