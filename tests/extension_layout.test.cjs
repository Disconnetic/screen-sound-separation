const assert = require("node:assert/strict");
const { computePanForDisplay, computePanForWindow } = require("../browser_extension/layout.js");

const twoWindows = [
  { id: 1, left: 0, width: 1920, state: "normal" },
  { id: 2, left: 1920, width: 1920, state: "normal" },
];

assert.equal(computePanForWindow(twoWindows, 1), -1);
assert.equal(computePanForWindow(twoWindows, 2), 1);
assert.equal(computePanForWindow([twoWindows[0]], 1), 0);
assert.equal(computePanForWindow(twoWindows, 999), 0);

const threeWindows = [
  { id: 1, left: 0, width: 1000, state: "normal" },
  { id: 2, left: 1000, width: 1000, state: "normal" },
  { id: 3, left: 2000, width: 1000, state: "normal" },
];
assert.equal(computePanForWindow(threeWindows, 2), 0);

const minimizedIgnored = [
  { id: 1, left: -5000, width: 1000, state: "minimized" },
  ...twoWindows,
];
assert.equal(computePanForWindow(minimizedIgnored, 1), -1);

const displays = [
  { id: "left", bounds: { left: -1920, top: 0, width: 1920, height: 1080 } },
  { id: "right", bounds: { left: 0, top: 0, width: 1920, height: 1080 } },
];
assert.equal(
  computePanForDisplay(displays, { left: -1800, top: 50, width: 1000, height: 800 }),
  -1,
);
assert.equal(
  computePanForDisplay(displays, { left: 200, top: 50, width: 1000, height: 800 }),
  1,
);
assert.equal(
  computePanForDisplay(displays, { left: -200, top: 0, width: 500, height: 800 }),
  1,
);

console.log("extension layout tests passed");
