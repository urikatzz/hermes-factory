# Factory Timeline and Model Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a live local Factory timeline with saved agent defaults and a task-wide override captured for each new attempt.

**Architecture:** Reuse the existing Python snapshot collector, aggregation, and vanilla JavaScript presentation. Add a separate model-policy store and local HTTP application. Supply model resolution through a narrow pre-spawn integration in Hermes, with Factory-specific policy in a standalone plugin rather than the core scheduler.

**Tech Stack:** Python 3.11+, SQLite, Python HTTP server, HTML/CSS/JavaScript, existing Hermes plugin interfaces; Python unittest and Node for dashboard checks, Hermes's prescribed test runner for its integration.

**Spec:** `docs/superpowers/specs/2026-10-16-factory-timeline-controls-design.md`

## Global Constraints

- “Changes affect future attempts; running and completed attempts retain their recorded model.”
- “Clearing the override restores each agent's default.”
- “Provider and model identity travel together.”
- “No commits or pushes without explicit permission.”
- Preserve existing explicit attribution, shared-session handling, separate cost categories, and missing-data labels.
- No paid model calls, installed-source changes, or live profile/scheduler activation during implementation validation.
- Required dependencies use constructor injection; presentation cannot mutate the database directly.
- Preserve snapshot generation without the server or Hermes installed.

## Findings and integration decision for review

Dashboard source is uncommitted in `/private/tmp/hermes-factory-dashboard`; preserve it before establishing the implementation checkout. This workspace contains documentation and copied reports only.

Inspected Hermes revision: `d923a5eb487a17c0a68801bba9ef0f56c81040a8`.

- `hermes_cli/kanban_db.py::set_model_override(conn, task_id, model, provider)` already persists per-card selections and emits an update event. Changing a running card applies on its next dispatch.
- `hermes_cli/kanban_db_dispatch.py::_worker_argv(task, profile_arg, hermes_home)` already passes model/provider to the worker.
- Dispatch claims a task and opens its run before invoking the spawn function. Existing worker-spawned observers run after process launch; they cannot safely enforce a model policy.
- The existing `spawn_fn` injection is useful for tests but does not automatically intercept the gateway's normal dispatcher.

Recommended integration: a narrow, synchronous `resolve_kanban_worker_model` plugin hook called before launch, plus its concrete standalone Factory consumer. The hook returns model/provider and provenance; Hermes persists provenance and passes the resolved values on a copy of the task. Exceptions abort launch through existing spawn-failure handling. Do not use the best-effort observer invocation path to swallow errors.

Alternative: update each existing child card using `set_model_override` and teach every stage creator to propagate overrides. This avoids a new hook but is vulnerable to dispatch/edit races and misses newly created or retried stages unless every creation path participates. The pre-spawn approach is recommended for the approved future-attempt semantics. This plan proposes that extension explicitly; it is not an existing Hermes capability.

## File structure

Paths below are relative to the dashboard implementation checkout unless marked **Hermes**.

- `factory_dashboard/model_policy.py`: immutable selection/policy records and precedence.
- `factory_dashboard/policy_store.py`: private SQLite configuration and revisioned writes.
- `factory_dashboard/model_catalog.py`: profile-scoped catalog and compatibility adapter.
- `factory_dashboard/live_service.py`: report/configuration application service.
- `factory_dashboard/http_server.py`, `scripts/serve_factory_dashboard.py`: loopback HTTP transport and entry point.
- `factory_dashboard/assets/timeline.js`, `timeline.css`, `live.js`: interval presentation, styling, refresh and forms.
- Existing `report.py`, `collector.py`, `renderer.py`, and assets: additive timeline/provenance integration; retain snapshot behavior.
- `integrations/hermes_factory_models/`: standalone plugin manifest/entry point and consumer adapter; no runtime monkeypatching.
- **Hermes** `hermes_cli/plugins.py`: register the concrete resolver hook name.
- **Hermes** `hermes_cli/kanban_db_worker_model.py`: synchronous resolver validation, metadata capture, task-copy construction.
- **Hermes** `hermes_cli/kanban_db_dispatch.py`: call resolver immediately before spawn within existing error handling.
- `tests/dashboard/test_model_policy.py`, `test_policy_store.py`, `test_model_catalog.py`, `test_live_service.py`, `test_http_server.py`, `test_timeline.py`, `test_factory_model_plugin.py`.
- **Hermes** `tests/cli/test_kanban_worker_model_resolution.py`.

## Review Focus

1. Two boards reuse task IDs: their overrides must remain independent (Tasks 1 and 3).
2. A retry starts while configuration changes: a single revision must determine its selection (Tasks 1 and 2).
3. Provider availability differs between roles: a task-wide choice must be valid for every participating profile (Task 3).
4. A failed refresh/save must preserve visible data and explicitly show its age or unsaved state (Tasks 4 and 5).
5. Several attempts overlap or lack timestamps: all remain selectable without invented execution durations (Task 5).

## Task 1: Persist model policy and resolve precedence

**Interfaces:** Define frozen `ModelSelection(provider: str, model: str)`, `ResolvedSelection(selection: ModelSelection, source: str, revision: int)` and `PolicySnapshot(revision: int, defaults: dict[str, ModelSelection], overrides: dict[tuple[str, str], ModelSelection])`. `ModelPolicy.resolve(snapshot, board_key, root_id, role) -> ResolvedSelection`; `PolicyStore.read() -> PolicySnapshot`; `set_default(role, selection, expected_revision) -> PolicySnapshot`; `set_override(board_key, root_id, selection_or_none, expected_revision) -> PolicySnapshot`.

- [ ] Write behavior tests asserting role A and B use different defaults; one root override supersedes both; clearing restores both; board B's identical root ID remains independent; missing defaults raise configuration errors.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p 'test_model_policy.py' -v`; confirm missing implementation failure.
- [ ] Implement immutable policy resolution with sources `agent_default` and `task_override`.
- [ ] Add store tests asserting persistence after reopen, revision conflict without overwrite, concurrent writers produce one winner, and rollback on failed save. Run to confirm failures.
- [ ] Implement SQLite transactions and compare-and-swap revision updates; store provider/model together, keep database and directory private, do not copy provider credentials. One store belongs to one selected Factory configuration; board keys use normalized source identity plus board ID.
- [ ] Run both new test modules; all assertions pass.

## Task 2: Capture selection at dispatch through a concrete plugin consumer

**Interfaces:** Hook receives `task`, `board`, and `workspace`; returns `None` for unmanaged tasks or a JSON-compatible mapping `{provider, model, source, revision, root_id}`. `prepare_worker_model(conn, task, workspace, board) -> Task` validates the result, records it under `task_runs.metadata.factory_model_selection`, and returns a copied task with resolved overrides. The standalone plugin resolves the exact Factory root using existing dashboard grouping semantics, reads one policy snapshot, and calls Task 1's resolver.

- [ ] Establish isolated dashboard and Hermes checkouts using the worktree skill; preserve all pre-existing uncommitted dashboard files. Read applicable Hermes CLI, cron, plugins, and tests instructions before editing. Record base revision and changed files.
- [ ] Write Hermes integration tests with a disposable home/board and intercepted spawn: resolved model/provider reach `_worker_argv`; metadata records the same revision before launch; an edit after resolution leaves the launched argv unchanged; retry resolves the newer revision; plugin failure prevents spawn and records failure; no registered resolver preserves current behavior.
- [ ] Run `scripts/run_tests.sh tests/cli/test_kanban_worker_model_resolution.py`; establish the failing behavior.
- [ ] Add the hook and narrow sibling implementation. Invoke registered synchronous callbacks using the existing plugin callback enumeration interface. Reject multiple non-null resolvers rather than selecting one arbitrarily. Merge metadata transactionally for the current run, preserving worker-session fields, and require successful persistence before launch. Never hold a database transaction while launching a process.
- [ ] Implement the standalone consumer, using profile-scoped configuration and an explicitly configured policy-store path. Store non-secret plugin settings in the existing configuration mechanism, not new environment variables. Validate every new role at dispatch, including roles added after an override was saved; incompatible settings fail launch explicitly. Existing native child-card overrides that conflict with managed policy must produce an actionable conflict rather than silently disappearing; matching values are allowed. Unmanaged tasks retain their original behavior.
- [ ] Test parent-stage inheritance, newly created stages, root attempts, unlinked tasks, identity collisions, conflicting child overrides, and broken policy storage. Managed policy-store errors fail closed; unrelated tasks stay unaffected.
- [ ] Run the targeted Hermes tests plus existing model-override and dispatch tests identified by the repository test inventory. Run its required lint checks. Produce a reviewable integration patch; do not install it.

## Task 3: Build catalog and live application service

**Interfaces:** `ModelCatalog.choices(profiles: tuple[str, ...]) -> list[ModelSelection]`; `validate(selection, profiles) -> None`; `LiveService.report() -> dict`; `configuration() -> dict`; `save_default(role, selection, revision) -> dict`; `save_override(root_id, selection_or_none, revision) -> dict`. Inject collector, builder, policy store, catalog, and selected board identity.

- [ ] Write tests proving catalog reads occur in the target profile scope; defaults initialize from explicitly configured agent models only; missing configuration reports an error; task overrides validate all participating profiles; revisions and board identity reach the policy store unchanged.
- [ ] Run the catalog/service test modules and establish failures.
- [ ] Implement a cached catalog using configured/local model metadata and Hermes's provider normalization. Do not call `curated_models_for_provider` indiscriminately: its implementation can perform network requests. No credential values leave the adapter. Validate existing reasoning/tool compatibility when supported by local metadata; explicitly reject known incompatibilities.
- [ ] Implement additive report fields for role defaults, task override, effective future selection, and captured dispatch provenance. Recorded session model remains the actual-use evidence; provenance labels the dispatch selection, not proof of provider execution. Preserve unknown historical models.
- [ ] Verify new tests and existing collector/aggregation tests pass, including shared usage and incomplete costs.

## Task 4: Serve report and narrow configuration endpoints

**Interfaces:** `create_server(service: LiveService, host: str, port: int) -> HTTPServer`. Endpoints: `GET /api/report`, `/api/configuration`, `/api/models`; `PUT /api/defaults/{role}`, `PUT /api/tasks/{root_id}/model`, `DELETE /api/tasks/{root_id}/model`. Mutations require expected revision and an application token.

- [ ] Write HTTP tests for report retrieval, valid writes, stale revision returning 409, invalid selection returning 400, unavailable source returning 503, unknown root rejection, and preservation of prior configuration on failure.
- [ ] Add tests rejecting non-loopback binding, foreign Host/Origin, missing token, invalid content type, oversized/malformed bodies, and traversal paths. Use disposable local servers and stores.
- [ ] Run HTTP tests to establish failures.
- [ ] Implement transport with explicit routes, bounded JSON requests, no permissive CORS, and no arbitrary filesystem/command endpoints. Serve only fixed bundled assets. Bootstrap a random per-server token for same-origin clients; validate Host and Origin on writes. Redact internal exception details from browser errors.
- [ ] Implement the CLI with existing explicit source-path options plus policy path and loopback port. Keep the existing snapshot CLI operational.
- [ ] Run service/HTTP tests; verify read-only refresh does not mutate board or policy data.

## Task 5: Timeline, model controls, and resilient refresh

**Interfaces:** `buildTimeline(reportTask, nowMillis) -> {lanes, attempts, events}` is a pure JavaScript transformation; `renderTimeline(container, timeline, onSelectAttempt)` renders it. `live.js` owns polling and configuration forms; existing formatters retain cost semantics.

- [ ] Add Node-driven behavior tests for distinct retries, overlapping attempts, mixed recorded models, queued work, missing timestamps, ongoing intervals, and rejected negative intervals. Assert unknown duration remains unknown.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p 'test_timeline.py' -v`; confirm failures.
- [ ] Implement the fixed lane column, horizontal execution bars, compact metrics header, and selected-attempt panel. Use existing stage/profile identity and safe text-node rendering. Provide separately selectable rows for overlaps; keyboard buttons and visible focus; narrow-screen stacking. Render events as points only when timestamped.
- [ ] Implement role-default forms and one task-wide override selector with reset. Show provenance and a preview of affected roles before Save. Preserve unsaved selections across refresh and show revision conflicts without auto-resubmitting.
- [ ] Poll every two seconds only while visible; avoid overlapping requests, refresh on visibility return, and show last successful refresh/error state. Preserve selected task/attempt and detail state. Static exports have no network activity or operational controls.
- [ ] Run timeline checks, all dashboard tests, and `node --check` on each modified JavaScript asset.

## Task 6: End-to-end evidence and delivery

- [ ] Generate a disposable fixture with two boards, different agent defaults, a task override, overlapping retries, one failed verdict on a completed card, unknown history, and partial/included costs.
- [ ] Exercise the server and disposable Hermes dispatch together with spawn intercepted before process creation. Verify saved override reaches all roles, reset restores defaults, concurrent configuration changes do not alter captured attempts, and failed saves leave the previous policy in force.
- [ ] Inspect the UI through the browser tools at desktop and narrow widths: timeline scrolling, detail selection, keyboard operation, default/override/reset, refresh failure, and save conflict. Record screenshots and results; explicitly report unavailable browser verification rather than claiming visual success.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p 'test_*.py' -v`, modified JavaScript syntax checks, and the targeted Hermes checks from Task 2. Regenerate snapshot fixtures to confirm standalone compatibility.
- [ ] Document startup, supported Hermes revision, disposable demonstration commands, patch/plugin installation order, revision-conflict handling, and rollback. Label controls as demonstration-only until the resolver is installed; never imply the live scheduler consumes a saved setting when integration is inactive.
- [ ] Perform final review against the spec and capture evidence in `docs/factory-timeline-controls-results.md`. Deliver source, sample, integration patch, and concrete activation instructions for review. Do not commit, push, or activate live changes without the required permission.

## Execution handoff

Recommended: native execution, implementing tasks sequentially in this session, followed by an independent final review. These tasks share model-policy and dispatch contracts; sequential ownership reduces interface drift. Subagent-driven execution is an alternative with a fresh implementer/reviewer per task and additional context cost.

Plan approval and execution-method selection precede product-code changes. The native path uses `superpowers:executing-plans`; the subagent path uses `superpowers:subagent-driven-development`.
