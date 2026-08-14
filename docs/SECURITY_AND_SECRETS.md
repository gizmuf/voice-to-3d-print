# Security and secrets

## Google Login and tenant isolation

Managed production must set `PULSAI_AUTH_REQUIRED=true` and
`GOOGLE_OAUTH_CLIENT_ID` to the public Web OAuth client ID registered for the
production origins. The backend verifies Google ID tokens; the frontend client
ID is not a secret. New design records receive the verified Google subject as
`owner_id`. Design lists, direct design URLs, local design artifacts, and GCS
design artifacts are checked against that owner. Legacy records without an
owner are intentionally inaccessible until an audited migration assigns them.

Set `CORS_ORIGINS` to the exact HTTPS frontend origin(s), for example
`https://3d.pulsai.app`. After Google verifies the user, the backend also sets a
short-lived Secure/HttpOnly/SameSite=None cookie so authenticated GLB downloads
and ordinary artifact links remain usable; API fetches still send the bearer
token. Never use wildcard CORS with this authenticated production mode.

If Cloud Run exposes the service while auth is required but the client ID is
missing, protected routes fail closed with HTTP 503. Never disable this gate to
recover a user's project; use an explicit owner migration instead.

## Invariants

- Repository files contain names and pointers only, never secret values.
- Cloud Run receives server credentials through Secret Manager references.
- VPS services receive credentials through `*_FILE` paths backed by systemd
  credentials, Docker secrets, or another approved secret mount.
- A customer Anthropic key is request-scoped BYOK data. It is held in the
  browser tab's memory, sent in `X-Pulsai-Anthropic-Key` over HTTPS, and must
  never be logged, persisted, copied into a design, or silently replaced with
  the platform key.
- CAD sandbox subprocesses receive only the allowlisted non-secret environment.
- Public safe mode executes only repository-controlled templates and
  deterministic macro code. Caller/model-authored Python remains disabled
  until a separate no-network, no-secret, non-root build worker is deployed.
- `PULSAI_ALLOW_PLATFORM_AI_SPEND=false` is the default and prevents Anthropic,
  Meshy, Tripo, Gemini, OpenAI image, and Deepgram calls from spending platform
  credentials. A production exception requires an authenticated entitlement,
  quota, rate limit, budget alert, and separate approval.
- `PULSAI_ALLOW_PUBLIC_ARTIFACTS=false` is the default. Cloud artifacts are
  private and served through the application; anonymous possession of an object
  URL must never be treated as tenant authorization.

## Cloud Run verification

Install and authenticate `gcloud` through the approved VPS access mechanism,
then run:

```bash
scripts/verify_cloudrun_secret_sources.sh pulsai-app us-central1
```

The script prints environment names and Secret Manager reference names only.
It never prints values. A plain value for any key/token/secret blocks deploy.

Before changing a service, discover its live revision, traffic, service
account, environment names, and existing secret references. Production changes
require separate approval. Missing provider secrets must be created from the
approved external source; never copy `.env`, key files, or credentials from a
laptop or another product repository.

## VPS secret files

The backend and STT support `NAME_FILE` for each credential, for example:

```text
ANTHROPIC_API_KEY_FILE=/run/credentials/pulsai-3d-backend/anthropic
DEEPGRAM_API_KEY_FILE=/run/credentials/pulsai-3d-stt/deepgram
```

If a configured file cannot be read, startup fails closed. A file value takes
precedence over a same-name plain environment value. Secret mounts must be
readable only by the service account and must not live in this checkout.

## Anthropic resilience and BYOK

The Messages SDK's hidden retry loop is disabled. Pulsai owns one bounded retry
budget with exponential backoff, jitter, `Retry-After`, a circuit breaker, and
the qualified fallback model configured by `ANTHROPIC_FALLBACK_MODEL`.

BYOK never falls back to the Pulsai platform key. Invalid credentials or a
customer rate limit produce customer-specific errors, leaving the design
unchanged. Usage records persist only model, token counts, estimated cost, and
`billing_source`; they never persist the key or its fingerprint.

## Public safe mode

Production must keep `PULSAI_PUBLIC_SAFE_MODE=true`. This disables legacy
project/workspace/model-processing and shared-provider routes whose original
records do not have trustworthy ownership. Modern Design records and artifacts
remain owner-scoped. `PULSAI_ALLOW_UNTRUSTED_CAD_CODE=false` prevents direct or
model-authored Python from executing with backend authority; built-in templates,
parameter edits and reviewed deterministic mesh macros remain available.

Do not disable public safe mode until legacy ownership migration, provider
admission quotas, and a separately isolated CAD build worker have passed a
security review. Random identifiers are locators, never credentials.

The evidence and proposed policy boundary are in
[`security-hardening/hardening.md`](security-hardening/hardening.md) and
[`security-hardening/proposals/tenant-authorization.md`](security-hardening/proposals/tenant-authorization.md).
