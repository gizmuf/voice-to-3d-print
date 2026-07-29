# Local backend autostart

## Current state

As of 2026-07-24, the per-user launchd service
`com.pulsai.3d.backend` is deliberately **disabled**. Do not assume that the
3dprint backend is running after login.

The project itself lives on ORICO at
`/Volumes/ORICO_APFS/Projects/3dprint`. The original path
`/Users/gizmuf/Dev/Xcode/3dprint` is a compatibility symlink and must be kept:
the LaunchAgent intentionally uses that stable path.

## What the service does

The plist is at:

`~/Library/LaunchAgents/com.pulsai.3d.backend.plist`

When enabled, it starts:

```text
backend/.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

It has both `RunAtLoad` and `KeepAlive`, so it starts at login and restarts if
terminated. Logs are `/tmp/pulsai-3d-backend.log` and
`/tmp/pulsai-3d-backend.err.log`.

## Enable when local 3dprint work resumes

```zsh
launchctl enable "gui/$(id -u)/com.pulsai.3d.backend"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.pulsai.3d.backend.plist"
launchctl kickstart -k "gui/$(id -u)/com.pulsai.3d.backend"
curl -fsS http://127.0.0.1:8000/health
```

## Disable again

```zsh
launchctl bootout "gui/$(id -u)/com.pulsai.3d.backend"
launchctl disable "gui/$(id -u)/com.pulsai.3d.backend"
```

Verify with:

```zsh
launchctl print-disabled "gui/$(id -u)" | rg 'com.pulsai.3d.backend'
lsof -n -P -iTCP:8000 -sTCP:LISTEN
```

Do not delete the plist just to stop the service: preserving it keeps the
known-good local backend setup reversible.
