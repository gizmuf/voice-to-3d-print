# Production startup validation

The production backend image starts `production_app:app`, not `app:app`.
`production_app.py` validates deployment invariants before importing the FastAPI
application. A failed check terminates the process before `/health` can become
available.

The gate runs when either:

- Cloud Run sets `K_SERVICE`; or
- `PULSAI_ENVIRONMENT=production` (or `prod`) is set explicitly.

Local development and ordinary CI imports remain unchanged.

## Required invariants

A production process must have:

- authentication enabled and insecure local mode disabled;
- public safe mode enabled so legacy/unsafe routes remain unavailable;
- a Google OAuth web client ID;
- explicit HTTPS CORS origins, never `*` or `null`;
- untrusted CAD execution disabled;
- platform-funded AI spend disabled;
- public artifacts disabled;
- a Firebase project for durable design state;
- a valid Fernet key for encrypted account BYOK storage;
- a storage bucket when `PULSAI_DURABLE_ARTIFACTS=true`.

Validation messages name settings only. They must never include credential
values, filesystem contents, or stack traces.

## Local verification

The normal local entrypoint remains:

```bash
PULSAI_AUTH_REQUIRED=false \
PULSAI_INSECURE_LOCAL_DEV=true \
PULSAI_PUBLIC_SAFE_MODE=true \
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

To exercise the production gate without serving traffic, provide production-like
environment values and import the production entrypoint:

```bash
PULSAI_ENVIRONMENT=production python -c 'import production_app'
```

Use placeholder identifiers only in a disposable environment. Never paste real
secret values into shell history; production secrets must remain Secret Manager
references as described in `docs/PRODUCTION_RUNBOOK.md`.
