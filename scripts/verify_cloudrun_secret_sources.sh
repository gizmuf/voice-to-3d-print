#!/usr/bin/env bash
set -euo pipefail

project="${1:-pulsai-app}"
region="${2:-us-central1}"
services=(pulsai-3d-backend pulsai-3d-stt)
secret_name_pattern='(^|_)(API_KEY|API_TOKEN|SECRET_KEY|CLIENT_SECRET|ADMIN_TOKEN|TOKEN|EMAIL_ALLOWLIST)$'
failed=0

command -v gcloud >/dev/null || {
  echo "BLOCK: gcloud is not installed"
  exit 2
}
command -v jq >/dev/null || {
  echo "BLOCK: jq is not installed"
  exit 2
}

for service in "${services[@]}"; do
  service_json=$(gcloud run services describe "$service" \
    --project="$project" \
    --region="$region" \
    --format=json)
  while IFS=$'\t' read -r name source; do
    [[ -z "$name" ]] && continue
    if [[ "$name" =~ $secret_name_pattern ]]; then
      if [[ "$source" == secret:* ]]; then
        echo "PASS: $service $name uses ${source}"
      else
        echo "FAIL: $service $name is a plain environment value"
        failed=1
      fi
    fi
  done < <(
    jq -r '
      .spec.template.spec.containers[].env[]?
      | [.name, (if .valueFrom.secretKeyRef then "secret:" + .valueFrom.secretKeyRef.name else "plain" end)]
      | @tsv
    ' <<<"$service_json"
  )
done

frontend_json=$(gcloud run services describe pulsai-3d-frontend \
  --project="$project" \
  --region="$region" \
  --format=json)
if jq -e '
  [.spec.template.spec.containers[].env[]?
   | select(.name | test("(^|_)(API_KEY|API_TOKEN|SECRET_KEY|CLIENT_SECRET|ADMIN_TOKEN|TOKEN|EMAIL_ALLOWLIST)$"))]
  | length > 0
' <<<"$frontend_json" >/dev/null; then
  echo "FAIL: frontend contains a secret-like environment variable, including a browser-public name"
  failed=1
else
  echo "PASS: frontend contains no secret-like environment variables"
fi

if (( failed )); then
  echo "BLOCK: one or more Cloud Run secrets are not Secret Manager references"
  exit 1
fi
echo "PASS: Cloud Run secret-source policy"
