# Production runbook (Google Cloud Run)

Production is the three Cloud Run services in project `pulsai-app`, region
`us-central1`. Always pass both flags explicitly. The VPS checkout is the
development and operations owner; moving runtime traffic to the VPS is a
separate migration and is not part of this runbook.

## Release gate

Do not deploy from an uncommitted tree. Record the release commit, obtain a
fresh backup, and require all free CI jobs to pass. Paid provider evals need a
separately approved budget. A release validates only the tested fixtures and
flows; it is not evidence that arbitrary CAD or a physical print is safe.

```bash
git status --short
git rev-parse HEAD
scripts/backup_gcp.sh pulsai-app
scripts/verify_cloudrun_secret_sources.sh pulsai-app us-central1
```

Before changing traffic, record current revisions, images, IAM, environment
variable names and secret references. Never print secret values.

```bash
for service in pulsai-3d-backend pulsai-3d-frontend pulsai-3d-stt; do
  gcloud run services describe "$service" \
    --project=pulsai-app --region=us-central1 \
    --format='yaml(status.traffic,status.latestReadyRevisionName,spec.template.spec.containers[0].image)'
done
```

## Required production policy

- `PULSAI_AUTH_REQUIRED=true`
- `GOOGLE_OAUTH_CLIENT_ID` is the public Web client ID for
  `https://3d.pulsai.app`
- `CORS_ORIGINS=https://3d.pulsai.app`
- `PULSAI_ALLOW_PLATFORM_AI_SPEND=false`
- `PULSAI_BYOK_ENCRYPTION_KEY` is a Secret Manager reference containing a
  dedicated Fernet key used only for account-stored customer provider keys
- `ANTHROPIC_PLATFORM_EMAIL_ALLOWLIST` is a Secret Manager reference containing
  only explicitly approved Google account emails; it never enables other paid
  providers
- `PULSAI_ALLOW_PUBLIC_ARTIFACTS=false`
- every variable containing a credential is a Secret Manager reference
- Cloud Run service accounts receive only the secret versions they use
- the backend stays at concurrency 1 until measured CAD build data justifies a
  change

`GOOGLE_OAUTH_CLIENT_ID` is an identifier, not a client secret. The current
Google Identity Services callback flow does not require a client secret.

## Build and deploy without traffic

Use an immutable release tag derived from the Git SHA. Source deploys create a
new revision; `--no-traffic` keeps the current production revision live while
the candidate is checked.

```bash
release_sha="$(git rev-parse --short=12 HEAD)"

gcloud run deploy pulsai-3d-backend --source=backend --no-traffic --tag=candidate \
  --project=pulsai-app --region=us-central1 \
  --revision-suffix="r-${release_sha}"

gcloud run deploy pulsai-3d-stt --source=stt-service --no-traffic --tag=candidate \
  --project=pulsai-app --region=us-central1 \
  --revision-suffix="r-${release_sha}"

backend_url="$(gcloud run services describe pulsai-3d-backend \
  --project=pulsai-app --region=us-central1 --format=json \
  | jq -r '.status.traffic[] | select(.tag == "candidate") | .url')"
stt_url="$(gcloud run services describe pulsai-3d-stt \
  --project=pulsai-app --region=us-central1 --format=json \
  | jq -r '.status.traffic[] | select(.tag == "candidate") | .url')"

gcloud run deploy pulsai-3d-frontend --source=frontend --no-traffic --tag=candidate \
  --project=pulsai-app --region=us-central1 \
  --revision-suffix="r-${release_sha}" \
  --set-build-env-vars="NEXT_PUBLIC_BACKEND_URL=${backend_url},NEXT_PUBLIC_STT_URL=${stt_url}" \
  --set-env-vars="NEXT_PUBLIC_BACKEND_URL=${backend_url},NEXT_PUBLIC_STT_URL=${stt_url}"
```

Apply runtime policy and Secret Manager mappings with `gcloud run services
update` or the deploy command. Use `--update-secrets`; never place a secret in
`--set-env-vars`, a YAML file, shell history, CI output, or Git.

For an integrated candidate test, build the frontend against the tagged backend
and STT candidate URLs. Once the tagged frontend URL exists, add that exact URL
temporarily to the candidate backend/STT CORS allowlist and create a fresh
no-traffic candidate revision. Remove the candidate origin before moving 100%
traffic; production CORS must return to only `https://3d.pulsai.app`.

## Candidate verification and traffic

Verify the tagged candidate URL with an authenticated test account. At minimum:

1. health and auth configuration;
2. Google login and owner isolation between two test identities;
3. CAD creation, deterministic edit, changed geometry hash and current preview;
4. revision persistence and private artifact download;
5. manufacturability check, slicing and ZIP/STL/G-code download;
6. save, reload, use, replace, and delete a customer key; verify that API
   responses and logs never contain its value;
7. an invalid customer key and an intentionally unavailable provider;
8. Cloud Logging errors and Secret Manager source verification.

Only then move traffic, one service at a time, and re-run public-domain smoke
tests. Keep the previous revision available for immediate rollback.

```bash
gcloud run services update-traffic SERVICE \
  --project=pulsai-app --region=us-central1 --to-revisions=REVISION=100
```

## Private GCS cutover

Do this last. First prove that every authenticated artifact URL is served by
the backend proxy or a short-lived signed URL. Then remove the bucket-level
`allUsers` object viewer binding and enforce Public Access Prevention. Verify
that a raw GCS object URL returns access denied while the authenticated app
still downloads the artifact.

If the authenticated flow fails, restore traffic to the previously recorded
revision. Do not make the bucket public as a shortcut.

## Rollback

Route 100% traffic back to the recorded ready revision. Rollback does not undo
Firestore/GCS writes, so use `docs/BACKUP_RESTORE.md` only after identifying
the exact affected project and recovery point. Never perform a broad restore
over healthy production data.
