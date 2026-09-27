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

// Keep the calculation testable with Node without changing how Chrome loads it.
if (typeof module !== "undefined") {
  module.exports = { computePanForWindow };
}
