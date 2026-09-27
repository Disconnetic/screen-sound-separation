# Browser tab capture experiment

This unpacked Manifest V3 extension tests whether two Chrome tabs can be replayed
with independent stereo panning. It does not communicate with the desktop app yet.

## Load it for development

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose this `browser_extension` directory.
4. Pin **Screen Sound Separation — Tab Test** to the toolbar.

## Test two tabs

1. Put one Chrome window on each monitor.
2. Play audio in a tab in each window.
3. Open each tab and click the extension icon once. Its badge should show `L`,
   `R`, or `C` according to the window position.
4. Confirm the tabs play on opposite sides at the same time.
5. Move a Chrome window and confirm the badge and pan update.
6. Click the icon again to release the tab and return it to normal Chrome audio.

Chrome requires a user gesture before a tab can be captured, so each managed tab
must be enabled explicitly. Closing a tab or disabling the extension stops its
capture and Chrome resumes normal playback.

