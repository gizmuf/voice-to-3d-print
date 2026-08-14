# Retired laptop backend autostart

The historical macOS `launchd` backend is retired. The canonical checkout,
development runtime, and validation environment are on the VPS at:

```text
/home/codex/workspace/repos/candao-3d-stack
```

Do not use a laptop checkout, compatibility symlink, laptop `.env`, or macOS
LaunchAgent as a source, runtime, credential input, or production dependency.
The supported service instructions are in
[`docs/RUNBOOK_LINUX.md`](docs/RUNBOOK_LINUX.md).

Production traffic still runs on the separately managed Cloud Run services.
Moving traffic to the VPS, changing DNS, or deleting a laptop checkout requires
an explicit live-state check and approval; this repository document performs no
such action.
