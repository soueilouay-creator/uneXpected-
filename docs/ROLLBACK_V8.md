# uneXpected v8 Rollback Procedure

## Rule

Never delete the previous AI Studio or Python runtime during the v8 test period. Rollback means returning the user-facing URL/entry point to the previous stable AI Studio deployment; it does not mean erasing the v8 branch or the new Neon database.

## Rollback triggers

- Unified service fails startup/readiness or repeatedly restarts.
- Public health is not 200 or reports non-durable storage.
- Runtime lifecycle fails or data becomes inconsistent.
- Database persistence/restore checks fail.
- Resource use causes repeated OOM/restarts on Render Free.
- Provider credentials or auth cannot be transferred safely.

## Procedure

1. Stop promoting v8 and leave the new service in place for diagnostics.
2. Point the owner back to the existing AI Studio URL `https://unexpected-ai-studio.onrender.com`.
3. Keep the existing Python test deployment `unexpected-v731-runtime-test` unchanged; it is an older integration-branch runtime and not automatically a provider-connected production fallback.
4. Do not connect the old app to the new v8 database unless a separately tested compatibility plan exists.
5. Preserve the v8 Render logs, deploy IDs, Git commit, Neon schema version and any workspace/database exports.
6. If v8 accepted workspace sync data, retain the Neon project. Export reconciled records before any schema change; do not delete the database during incident recovery.
7. Identify and fix the failed gate on a new feature branch or commit, rerun CI, deploy to the test service and re-run end-to-end checks before attempting cutover again.

## Recovery limitations

- Existing free Render filesystems are ephemeral; an old SQLite file may not be recoverable after prior redeploys/restarts.
- Manual phone backup files are independent data sources; preserve them as well as IndexedDB.
- Do not rotate old provider credentials until the new deployment has separately verified access, to avoid breaking rollback.
