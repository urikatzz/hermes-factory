# Factory Task Snapshots and Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make timelines read-only evidence, freeze settings for each Factory task, and submit prompts through the existing queue.

**Architecture:** A Factory sidecar store owns versioned defaults, immutable snapshots, submission identities, and task associations. Synchronous task-creation and pre-spawn integration attaches settings before eligibility and enforces them for each worker. The local dashboard reads historical session evidence and calls narrow defaults/intake APIs; it does not launch workers itself.

**Tech Stack:** Existing Python/SQLite dashboard, vanilla JavaScript/CSS, Hermes task API/plugin hooks and existing Factory intake; existing Hermes Python environment. No new framework or provider calls during tests.

**Spec:** `docs/superpowers/specs/2026-10-16-factory-task-snapshots-intake-design.md`

## Global Constraints

- Model, provider, and effort are frozen for the entire task, including later stages and retries.
- Unknown values remain Not recorded. Do not fill historical gaps from profile files or snapshots.
- Only profiles with recorded attempts have timeline lanes.
- Save future Factory defaults to the Factory settings store, not shared profile files.
- Non-Factory tasks retain native behavior.
- No credentials in snapshots, API responses, or logs.
- No commits or pushes without explicit user permission; do not execute skill-template commit steps.
- No real paid task is launched for testing. Use disposable homes/boards and intercepted worker launches.
- Do not interrupt existing workers during activation.

## Execution context and file map

Dashboard root D: `/private/tmp/hermes-factory-dashboard`, existing uncommitted isolated worktree. Hermes root H: `/private/tmp/hermes-timeline-integration`, prepared generic worker-model patch. Preserve both and record starting checksums; do not reset their uncommitted work. Installed source and scripts remain untouched until Task 8. Read applicable AGENTS.md before editing H.

New D modules:
- `factory_dashboard/task_settings.py`: immutable value types and validation.
- `factory_dashboard/task_settings_store.py`: defaults, snapshots, associations, submission records, activation state.
- `factory_dashboard/task_identity.py`: shared Factory root/stage identity parsing.
- `factory_dashboard/factory_creation.py`: synchronous creation-time snapshot policy.
- `factory_dashboard/task_submission.py`: intake validation, submission and status service.
- `factory_dashboard/hermes_intake.py`: narrow Hermes task/project adapter.
- `factory_dashboard/settings_migration.py`: dry-run/apply of legacy baselines.
- `factory_dashboard/assets/task_forms.js`: new-task/defaults dialogs separated from timeline rendering.
- `scripts/migrate_factory_task_settings.py`: explicit board-scoped migration CLI.

Modify existing D policy service, collector/report, plugin bundle/entry, HTTP handler, startup script, and timeline assets. Prepared copies of installed intake scripts go under `integrations/factory_intake/` for reviewable patch generation.

H changes: extend `hermes_cli/kanban_db_worker_model.py` for effort and snapshot provenance; add `hermes_cli/kanban_db_task_creation.py` for the synchronous creation hook; minimal wiring in `kanban_db.py`, `kanban_db_dispatch.py`, and `plugins.py`. Keep within Hermes file-size ratchets using focused sibling modules.

## Review Focus

1. A create call occurs inside an outer transaction: rollback must not leave a runnable task, and retry must not change an existing submission snapshot (Tasks 2–3).
2. User prompt contains fake Factory/snapshot headers: it must never select another task's settings (Task 3).
3. An unknown profile is added in a late stage: dispatch must stop clearly, never inherit current defaults (Task 4).
4. A task already has per-card model/effort overrides during migration: preserve them explicitly or block activation, never silently flatten them (Task 5).
5. The browser loses a successful submission response or the selected project disappears: recover one ticket by identity and preserve the user's prompt (Tasks 3 and 7).

## Contracts used across tasks

`RoleSettings(provider: str, model: str, effort: str)`; `DefaultsRevision(revision: int, roles: Mapping[str, RoleSettings])`; `TaskSnapshot(id: str, board: str, defaults_revision: int, created_at: str, origin: str, roles: Mapping[str, RoleSettings], legacy_card_settings: Mapping[str, RoleSettings])`. Return immutable copies. `origin` is `submission`, `direct_root`, or `legacy_migration`. Existing canonical `board_key(path, board_id)` defines board identity.

Submission payload: `submission_id` (UUID), `defaults_revision`, `title`, `project`, `type`, `prompt`, `acceptance`. Type is feature/bug/chore. Registered project aliases and the existing `new` convention are supported. Title is single-line, nonempty, <=200 characters; request and acceptance combined <=12,000 characters. Prompt is required. Header-like content remains inert request text.

Snapshot enforcement only consumes durable associations, not user-provided body fields. Task IDs in associations always include canonical board identity.

### Task 1: Immutable store and shared identity

**Files:** New `task_settings.py`, `task_settings_store.py`, `task_identity.py`; tests `test_task_settings_store.py`, `test_task_identity.py`.

**Interfaces:** `TaskSettingsStore.read_defaults() -> DefaultsRevision`; `save_default(role, settings, expected_revision) -> DefaultsRevision`; `prepare_submission(board, payload) -> dict`; `bind_task(board, task_id, snapshot_id, kind) -> None`; `snapshot_for_task(board, task_id) -> TaskSnapshot | None`; `read_submission(board, submission_id) -> dict | None`. Shared identity helpers accept explicit task mappings and read-only root lookup.

- [ ] Write tests `test_snapshot_survives_default_change`, `test_same_submission_returns_same_snapshot`, `test_changed_payload_reusing_id_rejected`, `test_board_isolation`, and `test_role_mapping_is_immutable`. Assert A retains medium after B's defaults revision changes to high.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p 'test_task_settings_store.py' -v`; expect missing module/behavior failures.
- [ ] Implement schema-versioned additive sidecar tables with foreign keys, private permissions, transactional revision checks and unique board/submission keys. Snapshot insertion is immutable; task association cannot be rebound. Hash canonical submission JSON excluding transport-only fields; record recovery state before external task creation.
- [ ] Implement identity tests for FACTORY roots, orchestrator+software-factory legacy roots, suffix `(t_hex)` stages and legacy `[t_hex]` stages; reject conflicting/ambiguous parent references rather than guess.
- [ ] Run the two new test files and existing report/plugin identity tests; expect all pass. Record checksums, no commit.

### Task 2: Capture before task creation becomes eligible

**Files:** H `hermes_cli/kanban_db_task_creation.py`, `kanban_db.py`, `plugins.py`; D `factory_creation.py`, plugin entry/bundle; H `tests/hermes_cli/test_kanban_task_settings_creation.py`.

**Interfaces:** Generic synchronous `before_kanban_task_create` hook receives the proposed full task mapping (with allocated ID), canonical board path/ID and creation/idempotency identity. It runs after existing idempotency lookup and before insertion/eligibility within the task transaction. Exceptions abort creation. Factory consumer `prepare_creation(task, board_path, board_id) -> None` uses the Task 1 store.

- [ ] Write failing integration tests for direct Factory-root creation, recognized intake ticket creation, idempotent re-create, nested transaction rollback, callback error, and unchanged non-Factory creation.
- [ ] Run H's prescribed `scripts/run_tests.sh tests/hermes_cli/test_kanban_task_settings_creation.py --file-retries 0` using the existing test interpreter; confirm intended failures.
- [ ] Implement the minimal generic hook with synchronous callback validation. Factory consumer durably binds the reserved task ID to its snapshot before the board transaction commits. A rollback may leave an inert orphan association, never runnable work. Existing submission identities always reuse their original snapshot; do not mutate the board from the callback.
- [ ] For ordinary Factory intake tickets, capture current defaults at ticket creation. For dashboard tickets, require the prepared submission identity. For `intake-<ticket_id>` roots, resolve the associated ticket and inherit its snapshot. Direct Factory roots capture defaults at creation. Unrecognized/missing associations fail closed when enforcement is enabled.
- [ ] Verify task creation via CLI and tools converges on the instrumented API; exercise both through their existing fixtures. Repeat new tests, existing creation/idempotency tests, and Hermes lint. Record any creation path not covered as an activation blocker.

### Task 3: Idempotent queue submission and intake propagation

**Files:** D `task_submission.py`, `hermes_intake.py`, `integrations/factory_intake/factory_ticket.py`, `integrations/factory_intake/factory_intake.py`; tests `test_task_submission.py`, `tests/hermes_integration/test_factory_submission.py`.

**Interfaces:** `TaskSubmissionService.preview(payload) -> dict`; `submit(payload) -> dict`; `status(submission_id) -> dict`. Adapter `list_projects() -> list[dict]`, `create_ticket(payload, submission_id) -> str`, `lookup_ticket(submission_id) -> str | None`, `lookup_root(ticket_id) -> str | None`. Inject adapter, store, catalog, and board identity.

- [ ] Write failing tests for invalid/stale inputs, double submit, lost response after ticket insertion, prompt text containing snapshot headers, deleted project, and original ticket/root returned on retry.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p 'test_task_submission.py' -v`; confirm failures.
- [ ] Implement validation and preview without worktree/network/worker activity. Reuse registered project resolution and existing preflight semantics. Invoke command APIs with structured arguments or subprocess argument arrays, never shell strings.
- [ ] Extend the narrow ticket adapter to use Hermes idempotency key `factory-submit-<UUID>`. Persist prepared snapshot first; the creation hook binds the actual ticket ID. On interrupted response, reconcile by that key. Return accepted ticket state even if later display refresh fails.
- [ ] Preserve existing intake root idempotency `intake-<ticket_id>`. Add descriptive snapshot reference to the root body only after obtaining its authoritative association; dispatch never trusts this text. Reject a mismatch before root eligibility. Do not run preflight's git fetch or intake during browser preview.
- [ ] Run disposable end-to-end queue tests with worker spawning and workspace/git side effects intercepted. Assert one ticket/root, correct snapshot, and no command interpretation from prompt strings.

### Task 4: Enforce frozen model and effort on every attempt

**Files:** H `kanban_db_worker_model.py` and resolver tests; D `factory_model_resolver.py`, plugin entry/bundle; D `tests/hermes_integration/test_factory_model_dispatch.py`.

**Interfaces:** Factory resolver returns `{provider, model, effort, source, revision, root_id, snapshot_id}`. Generic validator accepts snapshot fields when present, preserving compatibility for older unmanaged resolver results. `prepare_worker_model` returns a replaced Task including `reasoning_effort`; metadata stores the requested frozen selection once.

- [ ] Write failing tests for root A, late Fixer, retry A, and root B after a defaults edit: every A attempt uses A's model/effort while B uses B's. Test missing role/snapshot, native conflicting overrides, and immutable previously captured attempts.
- [ ] Run the focused Hermes resolver and plugin integration files using `scripts/run_tests.sh`; confirm expected failures.
- [ ] Replace mutable default lookup for managed tasks with Task 1 associations and shared identity. Apply captured legacy per-card settings when present. Validate effort using Hermes vocabulary; reject conflicting native overrides. Preserve session-link metadata and existing error handling.
- [ ] Assert intercepted default-launch arguments include `--reasoning` with snapshot effort plus correct provider/model. Confirm failed resolution launches no process. Requested settings and observed session values remain separate fields.
- [ ] Run focused dispatch, native overrides, and plugin discovery suites; run Hermes `scripts/check --base HEAD`. Report the previously reproduced macOS baseline systemd test failure separately if it remains, rather than suppress it.

### Task 5: Legacy migration and activation readiness

**Files:** D `settings_migration.py`, `scripts/migrate_factory_task_settings.py`; tests `test_settings_migration.py`.

**Interfaces:** `SettingsMigration.inspect() -> dict`; `apply(expected_inventory_digest) -> dict`; store `read_activation() -> dict` and `set_activation(state, expected_revision) -> None`. Required dependencies: board reader, actual profile reader, old policy reader, snapshot store.

- [ ] Write failing tests for completed-only tasks, queued/active roots, mixed model/effort card overrides, an already-running worker, orphan stages, and inventory changes between preview/apply.
- [ ] Run the migration test file and confirm failures.
- [ ] Implement read-only inventory and an idempotent apply that seeds future defaults from actual profile files, captures existing unfinished tasks as `legacy_migration`, and preserves explicit per-card settings. Do not rewrite task/session/run history. Stop on unresolved identities or contradictory policy instead of inventing provenance.
- [ ] Require creation/dispatch enforcement readiness and successful migration before defaults/submission mutations become available. Freeze new Factory claims during the short activation boundary while leaving running workers alone; inspect the installed dispatch mechanism before selecting its supported pause/reload operation. If no safe pause exists, keep mutations disabled and report the concrete blocker.
- [ ] Repeat apply in disposable storage and assert no new snapshot or changed baseline. Verify old profile-write endpoint cannot bypass migration gating.

### Task 6: Read-only evidence and operational APIs

**Files:** D `live_service.py`, `profile_service.py`, `http_server.py`, `report.py`, `collector.py`, `scripts/serve_factory_dashboard.py`; tests `test_http_server.py`, `test_report.py`.

**Interfaces:** GET `/api/defaults`, `/api/projects`, `/api/submissions/<UUID>`; PUT `/api/defaults/<role>` writes model/provider/effort with revision; POST `/api/submissions/preview`, POST `/api/submissions`. Existing task-model PUT/DELETE and shared profile-write endpoints return a clear retired/read-only error. Report adds requested snapshot summary separately from recorded attempts and queued submissions.

- [ ] Write failing API tests for activation gate, CSRF/Origin/Host protection, bounded payloads, stale revisions, duplicate POST, and attempts to mutate existing tasks through old endpoints.
- [ ] Run focused HTTP/report tests to verify failures.
- [ ] Compose the new defaults/submission services; retain current source collection and cost semantics. Serve only sanitized project aliases and model/effort data. Remove shared profile writes from this dashboard mode.
- [ ] Keep recorded model and effort exclusively tied to linked session evidence. Add read-only snapshot provenance, submitted time, and legacy-capture labels. Never merge current defaults into attempt objects.
- [ ] Run the full dashboard unittest suite and verify no regression in historical joins, unknown data, costs, and read-only archive behavior.

### Task 7: Timeline and New task interface

**Files:** D `assets/task_forms.js`, `assets/live.html`, `assets/live.js`, `assets/timeline.js`, `assets/timeline.css`; tests `test_timeline.py` and browser fixtures.

**Interfaces:** `FactoryTaskForms.openDefaults(context)` and `openNewTask(context)` consume injected API/report-refresh callbacks and current defaults/project data. Forms retain a submission UUID until success or an explicit new request; settings are frozen on submit with revision validation.

- [ ] Write failing timeline tests asserting multiple recorded model/effort pairs remain visible, unknown values stay unknown, and no default/override click target is rendered in a historical lane.
- [ ] Remove lane editors and existing-task override toolbar. Add Defaults for new tasks and New task actions outside task views. Attempt inspection stays interactive but read-only.
- [ ] Implement form fields and snapshot review from the spec. Require explicit Submit to Factory queue, show auto-start explanation, retain input on errors, recover by submission ID, and select the queued ticket/root after success.
- [ ] Preserve active dialogs, keyboard focus, selected attempts, and scroll across polling. Short bars expose full recorded settings in accessible labels and inspector. Mixed lanes say Multiple recorded settings.
- [ ] Verify with the supported browser tool at desktop and 390×844: historical selection cannot edit, defaults do not change old displays, stale save has useful feedback, invalid project keeps prompt, and a disposable submission appears once after a simulated lost response. No live production ticket is created for QA.
- [ ] Save screenshots for delivery; run Node syntax checks and the dashboard suite.

### Task 8: Integration review, installation, and delivery

**Files:** D integration patches/bundles; `docs/factory-timeline-controls.md`, `docs/factory-timeline-controls-results.md`; project artifacts under `/Users/example/orca/projects/hermes/artifacts/`.

- [ ] Review the final diff against the spec, particularly pre-claim ordering, snapshot identity, migration gates, profile-write retirement, and immutable recorded labels. Use the execution skill's required final review; if reviewer access fails, report it and perform documented author review rather than claim independent approval.
- [ ] Run final dashboard tests; targeted Hermes creation, dispatch, native override, and disposable intake integration suites; Hermes lint; patch applicability against the exact installed source revision. Do not apply a stale patch blindly.
- [ ] Produce backups and a dry-run migration report listing changed installed files and unfinished tasks. Inspect active workers and supported dispatcher pause/reload. Apply only the reviewed artifacts with any required filesystem escalation, install/enable the consumer in the owning dispatcher profile, and migrate before enabling dashboard mutations.
- [ ] Verify installed hook discovery and default arguments on a disposable board with intercepted spawn, then actual dashboard GET readiness/profile defaults. Confirm existing workers were not interrupted and no QA ticket entered the production queue.
- [ ] Package updated source and patches, migrations, rollback instructions, screenshots, and truthful test results. Rollback first disables defaults/submission writes, preserves snapshot storage, and prevents managed tasks from silently launching without enforcement; it is not just deleting the plugin.
- [ ] Deliver links to the running dashboard and documentation. No git commit/push and no real task submission without a user-authored task prompt.

## Plan self-review

Spec coverage: read-only history and unknowns (6–7); snapshot/default rules (1–4); all creation paths and duplicate recovery (2–3); migration and gate (5); authenticated loopback APIs (6); browser behavior (7); operational activation and rollback (8). Review-focus tests belong to Tasks 2/3/4/5/7 as marked. Interface names are shared above; source paths and tests are explicit. Installed file changes remain dependent on isolated verification, not on speculative patch application.

## Execution method

Preserve the user's previously selected native execution: primary agent implements tasks sequentially, with the execution skill's final review. This plan requires written-plan review before implementation. Do not ask the user to choose an execution method again.
