# Backup and restore

Production state consists of Firestore documents and private GCS artifacts.
The Cloud Run/VPS filesystem is a cache and is never a backup.

## Backup

Run from an approved operator identity with explicit project arguments:

```bash
scripts/backup_gcp.sh pulsai-app pulsai-app-assets BACKUP_BUCKET
```

Use a separate backup bucket with retention policy, object versioning, and a
service account that production cannot delete. The script waits for the
Firestore managed export to complete and then copies `three-d/` artifacts under
a timestamped prefix. A zero exit code is necessary but does not replace
object-count, retention, and isolated restore checks.

## Restore drill

Never drill into production. Create an isolated GCP project/database and target
bucket, then:

```bash
export PULSAI_CONFIRM_RESTORE=RESTORE-RESTORE_PROJECT
scripts/restore_gcp.sh \
  RESTORE_PROJECT \
  gs://BACKUP_BUCKET/three-d-backups/firestore/TIMESTAMP \
  gs://BACKUP_BUCKET/three-d-backups/artifacts/TIMESTAMP \
  RESTORE_TARGET_BUCKET
```

Acceptance checks:

1. Firestore import operation reaches `SUCCESS`.
2. Counts for designs, projects, jobs, revisions, state documents, and artifact
   objects match the backup manifest or expected snapshot.
3. Select three designs: load conversation, revision history, current GLB,
   restore one revision, rebuild, and confirm the mesh hash/artifact linkage.
4. Slice one known-safe design and verify the G-code estimate.
5. Confirm private objects are not anonymously readable.
6. Record RPO, RTO, operator, source snapshot, target project, discrepancies,
   and cleanup evidence.

## Production restore gate

A production import is a separately approved incident action. Freeze writes,
capture a pre-restore export, resolve exact source and target URIs, inspect IAM,
and prepare rollback. Firestore import merges documents and is not a substitute
for a tested deletion/reconciliation plan.

Current VPS limitation: `gcloud` and an approved GCP identity are absent, so
the scripts are syntax-checkable here but a real backup/restore drill remains
unverified.
