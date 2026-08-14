#!/usr/bin/env bash
set -euo pipefail

project="${1:?usage: restore_gcp.sh PROJECT FIRESTORE_EXPORT ARTIFACT_BACKUP TARGET_BUCKET}"
firestore_export="${2:?missing Firestore export URI}"
artifact_backup="${3:?missing artifact backup URI}"
target_bucket="${4:?missing target bucket}"
confirmation="${PULSAI_CONFIRM_RESTORE:-}"

if [[ "$confirmation" != "RESTORE-${project}" ]]; then
  echo "BLOCK: set PULSAI_CONFIRM_RESTORE=RESTORE-${project} after reviewing the targets"
  exit 2
fi

command -v gcloud >/dev/null || { echo "BLOCK: gcloud is not installed"; exit 2; }
gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . || {
  echo "BLOCK: gcloud has no active identity"
  exit 2
}

echo "Importing Firestore from ${firestore_export}"
gcloud firestore import "$firestore_export" \
  --project="$project" \
  --database='(default)'

echo "Restoring artifacts into gs://${target_bucket}/three-d"
gcloud storage rsync "$artifact_backup" "gs://${target_bucket}/three-d" \
  --project="$project" \
  --recursive

echo "PASS: restore commands completed; run acceptance checks before serving traffic"
