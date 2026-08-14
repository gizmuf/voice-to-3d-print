#!/usr/bin/env bash
set -euo pipefail

project="${1:-pulsai-app}"
source_bucket="${2:-pulsai-app-assets}"
backup_bucket="${3:-$source_bucket}"
stamp="${4:-$(date -u +%Y%m%dT%H%M%SZ)}"
firestore_uri="gs://${backup_bucket}/three-d-backups/firestore/${stamp}"
artifacts_uri="gs://${backup_bucket}/three-d-backups/artifacts/${stamp}"

command -v gcloud >/dev/null || { echo "BLOCK: gcloud is not installed"; exit 2; }
gcloud auth list --filter=status:ACTIVE --format='value(account)' | grep -q . || {
  echo "BLOCK: gcloud has no active identity"
  exit 2
}

echo "Exporting Firestore to ${firestore_uri}"
gcloud firestore export "$firestore_uri" \
  --project="$project" \
  --database='(default)'

echo "Copying immutable 3D artifacts to ${artifacts_uri}"
gcloud storage rsync "gs://${source_bucket}/three-d" "$artifacts_uri" \
  --project="$project" \
  --recursive

echo "PASS: Firestore export and artifact copy completed"
echo "Firestore: ${firestore_uri}"
echo "Artifacts: ${artifacts_uri}"
