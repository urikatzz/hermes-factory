# Factory task settings and dashboard intake — 17 October 2026

The live dashboard is http://127.0.0.1:4611. Use **Defaults for new tasks** to select a provider, model and effort for each profile. Use **New task** to enter a title, registered project (or New project), type, prompt and acceptance criteria, review all profile settings, and explicitly submit to the existing Factory queue. The scheduler may start accepted work automatically.

Every submitted ticket or directly created Factory root captures the complete defaults revision. Later stages and retries inherit that snapshot. Timeline lanes and attempt inspectors show session-recorded model and effort only; missing evidence remains Not recorded. A profile appears only when it has a recorded attempt. Changing defaults never rewrites old sessions or changes an existing task's later workers. Developer remains openai-codex / gpt-6-luna / medium.

#### Scenario: Defaults change after submission

- **GIVEN** task A captured Developer at medium effort
- **WHEN** defaults change to high and task B is submitted
- **THEN** A's later stages and retries keep medium
- **AND** B captures high; recorded attempts remain read-only

#### Scenario: A response is lost

- **GIVEN** a ticket was committed but the browser did not receive success
- **WHEN** the browser checks or retries its submission identity
- **THEN** it recovers the original ticket without submitting a duplicate

#### Scenario: A project disappears before ticket creation

- **GIVEN** a request was prepared but no ticket exists
- **WHEN** the user chooses Edit unqueued request
- **THEN** cancellation is serialized against ticket creation and the prompt remains editable under a fresh identity
- **AND** an already-created ticket is recovered instead of cancelled

## Verification and activation

- Dashboard suite: 86 tests pass.
- Hermes focused suite: 26 tests pass across creation, concurrent duplicate creation, rollback, immutable effort capture, native model/effort handling, plugin discovery and intake integration.
- Hermes `scripts/check --base HEAD`: 12 checks pass, including file-size ratchets.
- Fresh independent code review completed. Both Important findings were reproduced and fixed. Requested provider/settings visibility was also completed.
- Browser QA: read-only timeline; new defaults and submission dialogs; 390×844 form layout; lost-response recovery; disappeared-project recovery with editable prompt preserved. Exactly one ticket was created in the disposable QA board. No production QA ticket or paid worker was launched.
- Installed-source smoke test confirmed the original model and medium effort in launch arguments after defaults changed; zero worker processes launched.
- Live board migration found no unfinished roots or running workers. Existing board/session history was not rewritten.
- Hooks verified in the root home and all 11 named profile homes. Existing CLI and tool create paths both converge on the instrumented `kb.create_task` API.
- Hermes Desktop backend was gracefully restarted by its supervisor (old PID 26874 → new PID 12317). New-work pause was released after verification; activation is enabled.

An older broader suite reproduced a macOS/systemd infrastructure test failure on the untouched baseline; the focused suite above is green. Live provider acceptance was not tested with paid calls.

## Installed files and backups

- Dashboard: `/Users/example/.hermes/factory-dashboard`
- Immutable settings: `/Users/example/.hermes/state/factory/task-settings.db`
- Credential-free model catalog: `/Users/example/.hermes/state/factory/model-catalog.json`
- Consumer: `plugins/factory-models` in the root and every existing profile home; only the configured default board is claimed.
- Generic Hermes patch: `kanban_db.py`, `kanban_db_dispatch.py`, `plugins.py`, plus `kanban_db_task_creation.py` and `kanban_db_worker_model.py`.
- Intake compatibility: `scripts/factory_lib.py` accepts structured v2 tickets, preserving existing v1 channels.
- Backups, manifest, migration and activation records: `/Users/example/.hermes/backups/factory-snapshots-20261017-213525`.
- Exact installed Git base: `d923a5eb487a17c0a68801bba9ef0f56c81040a8`. No commits or pushes were made.

The dashboard process currently uses `/private/tmp/hermes-factory-sandbox-testenv/bin/python`. Keep that interpreter available for this process/restart command; the deployed dashboard and state themselves are in the persistent Hermes home. This task does not install a new startup service.

## Decisions and limitations

1. Recheck keyed creation inside the board write transaction so simultaneous requests cannot insert duplicate tickets. This is a small generic Hermes change, covered by a real concurrent-connection test.
2. Preserve uncommitted worktrees and source archives instead of making unauthorized commits. The worktrees and ledger therefore remain available.
3. Use structured JSON v2 ticket bodies so prompt text cannot override project/type routing. The shared parser must remain installed while such tickets are queued; v1 remains supported.
4. Bind the reserved task snapshot before insertion, but finalize the submission ticket ID only after board commit. Rollback can leave inert association records; it cannot change the prepared snapshot or leave a runnable task.
5. Provider and requested-settings visibility were treated as required user-facing behavior and completed during the review fix pass.
6. Deployment, migration, browser QA and packaging remained required after review; no paid provider calls were introduced for verification.

Deferred minor: legacy CLI ticket capture currently records its association as a root, so requested dispatch metadata can name the ticket in `root_id` rather than the later intake root. Snapshot identity, selected model/effort, actual task/run IDs and timeline joins are unaffected. This is an audit-label correction for follow-up.

## Rollback

Do not merely delete the plugin: that could allow managed tasks to run from mutable profile defaults.

1. Engage Hermes's supported new-work pause (`hermes pause`) and disable the settings store's activation flag. Keep all snapshot/submission state.
2. Inspect queued/running managed tasks. Let active workers finish; do not rewrite their sessions. Keep snapshot enforcement until managed work is finished or explicitly held away from dispatch.
3. Restore only the files listed in the backup manifest, comparing current files first so later user changes are not overwritten. Merge plugin configuration changes carefully; backups include configuration and must remain private.
4. Keep the v2 intake parser while structured tickets remain queued. Preserve the sidecar database and the credential-free catalog.
5. Restart the owning Desktop backend/gateway through its normal supervisor, verify which enforcement remains, and only release the pause when managed tasks cannot silently fall back to mutable defaults.
