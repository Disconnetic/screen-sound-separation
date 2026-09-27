# Browser tab capture experiment

This unpacked Manifest V3 extension lets the desktop development build control
independent stereo panning for Chrome tabs.

## Load it for development

1. Open `chrome://extensions`.
2. Turn on **Developer mode**.
3. Select **Load unpacked** and choose this `browser_extension` directory.
4. Select the extension card's reload button after changing its source.
5. Pin **Screen Sound Separation — Tab Test** to the toolbar.

Start the desktop app before using the extension. The app registers its local
development bridge automatically; Chrome connects to it without an administrator
prompt. A release build will install the same bridge through the app installer.

## Test two tabs

1. Put one Chrome window on each monitor.
2. Play audio in a tab in each window.
3. Select **Start routing** in the desktop app.
4. Open each tab and click the extension icon once. Its badge should show `L`,
   `R`, or `C` according to the window position.
5. Confirm the tabs play on opposite sides at the same time.
6. Move the separation slider and confirm both tabs follow it.
7. Move a Chrome window and confirm the badge and pan update.
8. Click the icon again to release the tab and return it to normal Chrome audio.
9. Stop routing and confirm every captured tab returns to normal playback.

Chrome requires a user gesture before a tab can be captured, so each managed tab
must be enabled explicitly. Closing a tab, stopping the desktop app, or losing the
native connection stops its capture and Chrome resumes normal playback.
