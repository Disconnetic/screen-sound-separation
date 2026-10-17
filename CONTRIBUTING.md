# Contributing

Thanks for helping improve Screen Sound Separation. This is a small, early-stage
Windows utility, so focused changes with clear reproduction steps are easiest to
review.

## Before opening a change

1. Open an issue for behaviour changes or anything that affects audio recovery.
2. Do not include private browsing data, machine-specific paths, packaged build
   output, or generated native-host registration files.
3. Keep browser capture opt-in and preserve the ability to restore normal audio.

## Development checks

Use Windows 10 or 11 with Python 3.11 or newer:

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
node tests\extension_layout.test.cjs
```

For UI changes, also launch the app, test Start/Stop routing, use **Restore audio
now**, and verify that closing and reopening the app leaves Windows channel
balance in a normal state. Describe the audio devices and applications you
tested in the pull request.

By contributing, you agree that your contribution is licensed under the MIT
License.
