# Factory Workflow Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manage versioned workflow templates from the dashboard and enforce each task's captured stages, reviews and bounded repairs.

**Architecture:** Immutable template revisions join the existing sidecar task snapshots. A Factory plugin controller owns managed-stage graph transitions in additive board tables, with synchronous Hermes mutation guards enforcing its contract. Dashboard forms edit future templates and preview captured workflows; historical attempts remain session-derived.

**Tech Stack:** Existing Python/SQLite Factory dashboard, vanilla JavaScript/CSS, Hermes plugin/task APIs and factory-worker handoff artifacts. No new UI framework or provider calls in tests.

**Spec:** `docs/superpowers/specs/2026-10-18-factory-workflow-templates-design.md` (approved 18 October 2026).

## Global Constraints

- Every managed task freezes the full workflow and provider/model/effort settings at submission or direct-root creation.
- Existing tasks without workflow snapshots retain legacy execution; do not infer or migrate their graph.
- Timeline lanes show only profiles with recorded attempts. Planned phases have a separate summary.
- Required preparation, implementation, at least one code reviewer and independent verification cannot be removed.
- Repair limit is an integer from zero to three. Worker retries are separate from repair cycles.
- Retain local-only delivery and existing approval/security constraints. No commits, pushes, publication or paid QA tasks.
- Preserve existing uncommitted work, snapshots, backups and live user settings. Do not reset either current source worktree.
- Hermes tests run through `scripts/run_tests.sh` with the existing test interpreter; never bypass the repository runner.
- Do not stop existing workers for activation. Keep new workflow submissions disabled until all enforcement routes pass verification.

## Execution context

D = `/private/tmp/hermes-factory-dashboard`, current isolated dashboard source. H = `/private/tmp/hermes-timeline-integration`, current isolated Hermes source. Installed dashboard is `~/.hermes/factory-dashboard`; installed Hermes is `~/.hermes/hermes-agent`. Verify worktree identities and installed/source checksums at execution start. If isolation requires another checkout, preserve the current uncommitted snapshot patch as the baseline rather than using pristine HEAD.

Test interpreter P = `/private/tmp/hermes-factory-sandbox-testenv/bin/python`. Hermes command prefix, run from H: `HERMES_PYTHON=/private/tmp/hermes-factory-sandbox-testenv/bin/python scripts/run_tests.sh`; use `--file-retries 0`. Dashboard tests run from D with `python3 -m unittest discover -s tests/dashboard -p '<file>' -v`. Node is available for behavior/syntax tests. Preserve the already selected native execution method, with one fresh final reviewer required by executing-plans.

Record source hashes and a baseline archive before edits. Save the approved spec and this plan in D's docs as well as the project workspace. Keep the execution ledger and uncommitted worktrees at delivery; no commit-based cleanup.

## File map and shared contracts

Create D modules under `factory_dashboard/`:

- `workflow_types.py`: immutable definition, binding, stage and decision value types.
- `workflow_templates.py`: revisioned definitions, per-type defaults and template validation.
- `workflow_capture.py`: atomic workflow/settings capture and intake selection.
- `workflow_state.py`: plugin-owned board tables and execution records.
- `workflow_handoffs.py`: typed normalization of existing worker metadata and findings.
- `workflow_gate.py`: pure gate policy, manifest/acceptance/no-progress checks.
- `workflow_controller.py`: transactional, idempotent next-phase reconciliation.
- `workflow_guards.py`: creation/mutation/claim/complete policy for managed tasks.
- `workflow_cards.py`: established stage body/workspace/artifact contracts.
- `workflow_service.py`: HTTP-facing template and report operations.
- `assets/workflow_forms.js`: editor and workflow summary rendering.

Modify the existing sidecar store/types, submission service, creation consumer, plugin entry/bundler, snapshot service, HTTP server, startup composition and task forms. Stage copies of installed worker/orchestrator skills and affected SOUL files under D `integrations/factory_workflows/`; install only at the final activation task.

Create H `hermes_cli/kanban_db_mutation_guard.py`; minimally wire existing task-creation, claim, mutation, dependency and completion owners and register a generic hook. Keep core free of Factory-specific states or profile names.

Contracts:

- `StageSpec(key: str, kind: str, profile: str, instructions: str)`; kinds `prepare`, `implement`, `review`, `verify`, `repair`.
- `WorkflowDefinition(template_id: str, revision: int, name: str, description: str, task_type: str, prepare: StageSpec, implement: StageSpec, reviewers: tuple[StageSpec,...], verify: StageSpec, repair: StageSpec, max_repairs: int)`.
- `WorkflowBinding(snapshot_id: str, definition: WorkflowDefinition)`. Existing TaskSnapshot gains optional workflow data; absent means legacy, never latest-default lookup.
- `WorkflowTemplates.list(include_archived=False) -> list[dict]`, `get(template_id, revision=None) -> WorkflowDefinition`, `save(document, expected_revision) -> WorkflowDefinition`, `archive(template_id, expected_revision) -> None`, `set_type_default(task_type, template_id, expected_revision) -> dict`.
- `capture_submission(board, payload) -> dict` preserves existing submission keys and adds `workflow_id`, `workflow_revision`, and `workflow_defaults_revision`. Capture model defaults and selected workflow in one sidecar transaction. A missing explicit selection is resolved through the versioned type-default mapping at creation.
- `WorkflowState.ensure_root(conn, root_id, binding) -> None`, `read_root(conn, root_id) -> dict`, `stage_for_task(conn, task_id) -> dict | None`.
- `normalize_handoff(task, run, expected_stage) -> StageResult`; `evaluate_cycle(writer, readers, previous_cycle, max_repairs, repairs_used, context) -> GateDecision`. Decisions `wait`, `pass`, `repair`, `human_review`, `blocked`.
- `WorkflowController.reconcile(conn, root_id) -> dict`: owns one write transaction or joins the caller's supported transaction; never launches workers or performs network/filesystem artifact reads under the board lock.
- Generic `before_kanban_task_mutation(conn, operation, task_id, proposed, board, board_path)` callbacks are synchronous, exceptions veto within the write transaction. `conn` is a trusted plugin transaction handle, not serialized external input.

Template bounds: name 1–100 characters, description at most 1,000, each instruction at most 4,000, all template instructions at most 20,000. Use server-generated UUIDs and stable stage keys; enforce unique reviewer profile and reviewer key. Profiles and capabilities come from the allowlisted Factory catalog/contract registry, not caller-provided capability flags.

## Review Focus

1. A stale worker completes after a repair/retry supersedes its run: it must not satisfy the current gate (Tasks 4–5).
2. An ordinary task references a managed root ID in its title, or a managed task is renamed/reassigned: titles must not grant controller authority and native tasks must remain native (Tasks 2–3).
3. A crash occurs between sidecar capture, root insertion and initial stage materialization: recovery must preserve one snapshot and one logical stage (Tasks 2 and 5).
4. An administrative force/update path removes dependencies or finishes a managed root: required evidence must remain enforced across CLI/tools/web paths (Tasks 3 and 6).
5. Type defaults or templates change during a lost-response submission or editing dialog: retain the accepted definition and user prompt, with no duplicate task (Tasks 2 and 7–8).

---

### Task 1: Versioned templates and capability validation

**Files:** Create D `workflow_types.py`, `workflow_templates.py`; modify `task_settings_store.py`; test `tests/dashboard/test_workflow_templates.py`.

**Interfaces:** Produces the StageSpec/WorkflowDefinition types and WorkflowTemplates methods above. Sidecar schema upgrades are additive and reject unsupported newer versions without resetting their version marker.

- [ ] Write failing tests `test_presets_and_capabilities`, `test_revision_is_immutable`, `test_archive_requires_replacement_default`, `test_invalid_writer_review_and_limits`, `test_existing_settings_database_upgrade`. Assert the exact three approved presets; max repairs accepts 0 and 3 and rejects -1/4/bools; Developer cannot review its own implementation; historical revisions survive edits and archive.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p 'test_workflow_templates.py' -v`. Expected: missing module/behavior failures, not fixture/import-environment failures.
- [ ] Implement immutable template/revision and per-type-default tables alongside the existing snapshot store. Seed Feature (Architect/Developer/Claude+Security+UX+UI/Verifier/Fixer), Bug fix (Fixer/Fixer/Claude+Security/Verifier/Fixer), Chore (Developer/Developer/Claude/Verifier/Fixer), all with three repairs. Seed once without overwriting edited defaults.
- [ ] Implement the capability registry and validation bounds from shared contracts. Archive is reversible; referenced revisions remain retrievable. Concurrent stale saves return RevisionConflict.
- [ ] Repeat the task test and existing task-settings tests. Expected: all pass; unchanged existing snapshot documents decode as legacy.

### Task 2: Freeze workflow and model settings together

**Files:** Create D `workflow_capture.py`; modify `task_settings.py`, `task_settings_store.py`, `task_submission.py`, `factory_creation.py`, `hermes_intake.py`, and staged `integrations/factory_intake/factory_lib.py`; tests `test_workflow_capture.py` and `tests/hermes_integration/test_workflow_capture.py`.

**Interfaces:** Consumes Task 1 definitions/default mapping. Produces WorkflowBinding in each new snapshot; `capture_submission` above. Durable board/snapshot association is the authority, not root/stage body text.

- [ ] Write failing tests `test_capture_freezes_both_revisions`, `test_recovered_submission_ignores_later_edits`, `test_direct_root_uses_type_default`, `test_intake_inherits_ticket_workflow`, `test_legacy_stays_legacy`, `test_outer_rollback_preserves_prepared_workflow`, `test_prompt_cannot_choose_workflow`.
- [ ] Run the dashboard capture test and H runner on D integration test. Expected: assertions fail for absent workflow capture.
- [ ] Extend preparation to atomically validate/capture role defaults, template definition and type-default revision. Preserve previous payload identity recovery and cancellation behavior. Explicit invalid/archived template selections fail; stale unsent selection requires refreshed preview. Existing prepared submissions lacking workflow remain legacy rather than being upgraded on retry.
- [ ] Extend structured intake metadata for validated workflow references while retaining existing v1/v2 submissions. Resolve explicit CLI/chat selections from parsed intake control metadata; keep the request field inert. Intake roots inherit the ticket association without recapturing. Bind new stage identity through controller-issued registration rather than title matching alone.
- [ ] Run both test files plus prior creation/submission suites. Expected: old/late/retried tasks retain both snapshots, zero paid launches, and all existing submission recovery tests pass.

### Task 3: Transactional Hermes guards and authoritative managed identity

**Files:** Create H `hermes_cli/kanban_db_mutation_guard.py`; modify `kanban_db.py`, `kanban_db_task_creation.py`, `plugins.py`, and focused sibling mutation owners discovered by the audit. Create D `workflow_state.py`, `workflow_guards.py`; modify plugin entry/bundler. Tests H `tests/hermes_cli/test_kanban_mutation_guards.py`, D `tests/hermes_integration/test_workflow_guards.py`.

**Interfaces:** Produces the synchronous generic mutation hook and WorkflowState methods. Plugin tables: `factory_workflow_roots`, `factory_workflow_stages`, `factory_workflow_events`, with unique logical stage `(root_id, stage_key, cycle, evidence_retry)` and explicit active run identity. Store the workflow snapshot ID on each managed root.

- [ ] Audit every supported mutation path: create, patch/update, assignment, model/effort, dependency link/unlink, claim/review claim, completion/force completion, unblock/reopen, archive/delete and bulk actions. Record entry point and common transactional owner in `docs/workflow-mutation-coverage.md`. Inspect CLI, tools and web callers. Any uncovered route blocks activation.
- [ ] Write failing tests `test_guard_exception_rolls_back`, `test_async_guard_rejected`, `test_bulk_and_force_cannot_bypass`, `test_removed_dependency_still_cannot_claim`, `test_managed_identity_survives_rename`, `test_native_reference_is_not_managed`, `test_unregistered_extra_stage_is_rejected`. Native mutations without a claiming consumer must behave exactly as before.
- [ ] Run the two guard test files through H's runner. Expected: forbidden mutations currently succeed or the new hook is absent.
- [ ] Wire the generic guard inside existing write transactions before state changes. Recheck decision inputs under the write lock. Use focused sibling helpers to respect core file-size ratchets. Do not emit after-commit callbacks while the transaction is uncommitted.
- [ ] Implement trusted controller authorization using an internal scoped context, never an API/body flag. Protect managed assignment, graph, snapshot and success state. Guard cancellation/archive policy so current evidence cannot be reused afterward. Permit comments, inspection and legitimate worker evidence reporting. Exceptions must retain actionable diagnostics without leaking request bodies.
- [ ] Run guard tests, existing native mutation tests identified by the audit, and `/private/tmp/hermes-timeline-lintenv/bin/python scripts/check --base HEAD`. Expected: all new/native contract tests and all lint checks pass. Record any known untouched baseline failure separately.

### Task 4: Worker contracts and deterministic evidence gates

**Files:** Create D `workflow_handoffs.py`, `workflow_gate.py`, `workflow_cards.py`; stage worker/orchestrator skills and affected profile role instructions in `integrations/factory_workflows/`; tests `test_workflow_gate.py`, `test_workflow_cards.py`.

**Interfaces:** Produces StageResult/GateDecision and the normalization/evaluation signatures above; `build_stage_card(definition, stage_key, cycle, context, inputs) -> dict` returns validated Hermes create arguments. Keep current factory-worker/v2 compatibility for legacy tasks; managed metadata adds a distinct workflow contract version and stage/run identity.

- [ ] Write table-driven failing tests for current verdict vocabulary and findings severity, missing AC results, mismatched manifest, stale run, invalid reader first/second response, writer BLOCKED, truncated findings, environment restrictions, previous rejected/unfixable findings, zero/three repairs, and required artifact references.
- [ ] Run `test_workflow_gate.py` and `test_workflow_cards.py`. Expected: missing behavior failures.
- [ ] Implement normalization for `contract`, `root`, `stage`, `cycle`, `verdict`, `manifest_sha12`, `ac_ids`, `ac_results`, findings, artifact references, blocked tools and release audit. Verify run identity from board state, not worker-supplied IDs. Gate only current completed attempts; historical or manually synthesized no-worker completions cannot count.
- [ ] Encode existing blocker/high/acceptance-linked medium, waivers, no-progress and Unity environment exception rules as explicit policy tests. Invalid readers get at most one evidence retry per logical stage/cycle; invalid writers or repeated invalid readers escalate. Preserve artifact references for reproduction; do not read arbitrary artifact paths under database locks.
- [ ] Build preparation cards that always emit PLAN.md, AC IDs and include-list requirements. Fixer diagnosis and Developer chore preparation run in scratch/read-only mode; later implementation/repair use the project dir. Adjust profile/worker contracts so stage-specific preparation is supported without granting writers review authority. Selected reviewers and Verifier run in scratch against one manifest.
- [ ] Rerun both tests and existing report/evidence tests. Expected: all pass; rendered cards satisfy workspace, handoff and local-only delivery invariants.

### Task 5: Idempotent controller and bounded repairs

**Files:** Create D `workflow_controller.py`; extend `workflow_state.py`, `workflow_guards.py` and plugin registration; tests `test_workflow_controller.py`, `tests/hermes_integration/test_workflow_controller.py`.

**Interfaces:** Consumes Tasks 1–4; produces `WorkflowController.reconcile(conn, root_id) -> dict`. Root phases: `preparing`, `implementing`, `reviewing`, `repairing`, `human_review`, `blocked`, `delivered`. Events identify the accepted source run and gate decision.

- [ ] Write failing scenario tests for all three presets; concurrent double reconciliation; crash/rollback before/after each materialization; delayed duplicate events; partial parallel review completion; stale completion after retry; reader evidence retry; blocked preparation; each repair limit; human resume; native/legacy isolation.
- [ ] Run dashboard and H integration controller suites. Expected: missing controller/graph failures.
- [ ] Implement transactional stage creation and dependencies using stable logical keys and controller authorization. Materialize preparation, then implementation, then selected parallel reviewers/verification. Managed roots are held from legacy root-worker graph creation; the controller completes passing roots, while the orchestrator's chat role remains available for explanations and human-decision relay.
- [ ] On current gate failure create one repair writer, then the entire selected review/verification panel. Increment repair count once per new repair phase. Normal worker crash retries do not advance the cycle. Escalate on exhaustion/no-progress or invalid evidence. Human resume records the explicit note and may resume/retry within the frozen rules; it cannot silently waive required stages or extend the frozen limit.
- [ ] Register post-commit lifecycle observers for prompt reconciliation and a dispatch-tick recovery scan for roots needing reconciliation. Bound each scan and avoid reprocessing unchanged roots. A crash or observer failure must leave durable work that the next tick can reconcile. Existing worker processes are launched only by Hermes.
- [ ] Rerun controller/guard suites with intercepted spawns. Expected: exactly one logical stage per transition, no early delivery, no paid process starts, and correct frozen model/effort on all materialized stages.

### Task 6: Complete route enforcement and legacy compatibility

**Files:** Extend the mutation coverage document, integration fixtures, plugin bundle and startup readiness; tests `tests/hermes_integration/test_workflow_mutation_routes.py`, `test_workflow_legacy.py`.

**Interfaces:** Produces `workflow_readiness() -> dict` with installed contract/schema versions, required hook discovery and activation flag. This is a deployment gate, not a claim that merely importing a module proves enforcement.

- [ ] Write failing tests that attempt the same graph bypass through CLI, tool, web patch, bulk mutation and force completion. Test a native task with `(t_hex)` referencing a managed root, an old Factory root without a workflow, and an unknown new stage profile.
- [ ] Run both integration files through H's runner. Expected: incomplete route wiring fails visibly.
- [ ] Close missing routes using the common transactional owners from Task 3. Preserve legacy skill behavior and old role snapshots; managed guards must not attach new definitions to legacy roots. Reject new managed creation when enforcement is unavailable rather than falling back to the old orchestrator graph.
- [ ] Test reboot/discovery in every configured creating/dispatching home against disposable boards. Verify intended captured role settings actually reach default-launch arguments, not merely preview output.
- [ ] Run the complete new Hermes workflow integration suite plus prior snapshot/native-override tests and lint. Expected: green suites and no uncovered mutation path in the coverage document.

### Task 7: Template APIs, submission preview and workflow reports

**Files:** Create D `workflow_service.py`; modify `snapshot_service.py`, `http_server.py`, `task_submission.py`, startup composition and report enrichment; tests `test_workflow_http.py`, `test_workflow_reports.py`.

**Interfaces:** GET `/api/workflows`, GET `/api/workflows/<id>` (optional validated revision); POST `/api/workflows`; PUT `/api/workflows/<id>`; POST `/api/workflows/<id>/archive`; PUT `/api/workflow-defaults/<type>`; POST `/api/workflows/preview`. Submission preview returns captured candidate definition/role settings and all required revisions. Existing root reports gain `workflow` with captured name/revision, planned phases and current state.

- [ ] Write failing tests for Host/Origin/token checks, payload bounds, stale revisions, archive/default conflicts, missing hooks/readiness, explicit invalid template, uneditable old root workflows, and forged provider/capability fields.
- [ ] Run both test files. Expected: new routes/fields absent.
- [ ] Implement narrow services using the existing dependency injection style. Preview validates only; it creates no task/workspace and makes no provider calls. Existing submission idempotency covers workflow selections. List/get responses contain no secrets and no mutable-default reconstruction of historical workflow.
- [ ] Add separate workflow summary state to reports, preserving observed attempts/model/effort and current cost semantics. Unknown legacy data stays labeled Legacy workflow. Archived definitions remain readable by captured revision.
- [ ] Run full dashboard unittest suite. Expected: new API tests and all previous snapshot, recovery, read-only history and cost tests pass.

### Task 8: Dashboard editor and new-task workflow selection

**Files:** Create D `assets/workflow_forms.js`; modify `task_forms.js`, `live.js`, `live.html`, `timeline.css`; tests `test_workflow_ui.py` and disposable browser fixtures.

**Interfaces:** `FactoryWorkflowForms.openEditor(context)` and `renderSummary(container, workflow)` use injected API/refresh callbacks. New task context carries selected template ID/revision and mapping revision until accepted or explicitly cancelled. Preserve current same-ID lost-response recovery.

- [ ] Write failing Node/DOM tests for preset display, capability-filtered choices, explicit review membership, independent verification, captured-vs-current revision labels, and no fabricated timeline lanes.
- [ ] Run UI test file. Expected: absent editor and workflow-selection behavior.
- [ ] Implement template list/create/duplicate/edit/archive and type-default selection. Use ordered phase cards and selected reviewers, not arbitrary graph editing. Inline validation explains invalid combinations. Form state, keyboard focus and scroll survive polling.
- [ ] Add workflow selection/preview to New task. Type suggests its default until the user explicitly selects another. A later type change retains an explicit choice and displays a mismatch note. Stale template/default revisions preserve prompt and require refreshed review. Existing task views expose captured workflow read-only.
- [ ] Browser-test desktop and 390×844 using disposable storage: save/duplicate/archive, stale save, default change during preview, lost successful response, cancel/edit unqueued request, and an old task retaining its original workflow after edits. Inspect planned summary vs actual attempt lanes. Never submit a production QA task.
- [ ] Run Node syntax checks and full dashboard suite; save screenshots. Expected: green tests, accessible form controls, no accidental template save on polling or modal close.

### Task 9: Review, migration gate, activation and delivery

**Files:** Integration bundle/patches, installation/migration scripts under D `scripts/`, project `artifacts/factory-workflows-2026-10-18/`, docs `factory-workflows.md` and `factory-workflows-results.md`.

**Interfaces:** Add an explicit workflows-enabled flag separate from existing model/default activation. Defaults and existing snapshot enforcement keep working until workflow activation is verified.

- [ ] Complete the required fresh whole-change review using the approved spec, this plan, mutation coverage and ledger rulings. Re-grade findings by user impact and fix blocking findings with regressions before installation. No code edits by reviewer; no unauthorized commits/pushes.
- [ ] Run full dashboard tests, all new workflow integration tests, existing snapshot/native task tests, Hermes lint, JavaScript checks and patch applicability against the exact installed source. Record command output and artifact hashes.
- [ ] Inventory active work and capture backups of changed code/config/skills. Seed templates and default mappings without changing old task snapshots. Preserve legacy tasks; do not rewrite their graph. Pause new claims using supported controls while preserving running workers.
- [ ] Install generic guards, plugin controller, dashboard and stage contracts into owning homes. Restart/reload only idle owning processes as needed; if safe activation cannot be established, keep new workflow submissions disabled and report the specific blocker. Do not assert success from import-only checks.
- [ ] Verify installed route guards and frozen worker arguments on disposable boards, then dashboard readiness/defaults via read-only production APIs. Enable templates only after all checks; release only the pause created by this deployment. Confirm no QA ticket entered the production board.
- [ ] Package source archives, exact patches, private-backup locations (not secret backup contents), tests, screenshots and rollback instructions. Rollback disables new workflows, retains state and holds/enforces managed work before removing any guard. Keep user branches/worktrees uncommitted.

## Plan self-review

Coverage: editor/presets/capabilities (1,8); joint snapshot/intake and legacy compatibility (2,6); transactional enforcement and controller ownership (3,5,6); preparation artifacts, evidence, manifests and bounded repairs (4,5); protected APIs and actual-only timelines (7,8); recovery/activation/rollback (9). All five review-focus cases have named owner tests. Shared signatures and stage keys are defined before consumption. No speculative worker launch or Git-write step is included.

## Execution handoff

Preserve native execution: implement in this session with the execution ledger and one independent final review. The written plan awaits user review before implementation, as required by writing-plans. Do not ask the user to choose native versus delegated execution again.
