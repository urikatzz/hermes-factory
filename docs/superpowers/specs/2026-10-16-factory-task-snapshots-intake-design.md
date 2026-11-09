# Factory task settings snapshots and dashboard intake

## Approved intent

The user wants the timeline to show the model and reasoning effort each profile actually ran with, without controls that appear to edit historical runs. Defaults may be changed only for new tasks. The user also approved submitting prompts through a New task form using the existing Factory queue.

This design supersedes the earlier rule that retries inherit the latest defaults. Model, provider, and effort are frozen for the entire task, including later stages and retries. No commits or pushes are authorized.

## Current behavior and gaps

Dashboard source is in `/private/tmp/hermes-factory-dashboard`. Its loopback server reads the actual board and supports live profile model/effort edits. Attempt bars already read model and effort from linked sessions, but lane headings show editable current defaults. Task-wide model overrides are staged, not active. The prepared generic Hermes dispatch hook captures model/provider per attempt but is not installed and does not yet enforce task-level effort snapshots.

The existing `factory_ticket.py` creates a triage ticket. `factory_intake.py` promotes it to a root with an idempotency key derived from the ticket ID, creates the existing workspace isolation, and lets the normal dispatcher run it. It does not currently carry an immutable model/effort snapshot. Its preflight and intake can access git/network and create worktrees; these are execution effects, not harmless form previews.

## Chosen approach and alternative

Use the existing Factory intake and worker dispatch with a small snapshot store and narrow integration points. This preserves scheduling, project isolation, review stages, and capacity rules. A dashboard-only visual change would be simpler, but would not prevent later defaults from changing pending stages. Direct worker launch from the dashboard is rejected because it duplicates the queue and bypasses its capacity/isolation behavior.

Presentation, snapshot policy, persistence, intake adaptation, and dispatch adaptation remain separate, with required dependencies passed through constructors. No generic command execution endpoint.

## User interface

### Read-only task timeline

- Remove model/effort editing and task override/reset actions from selected-task timelines, including their mutation endpoints for existing tasks.
- Agent lanes contain role labels and recorded setting summaries only. If attempts differ, show Multiple recorded settings; never select one and imply it applied to all attempts.
- Every attempt has recorded model and effort labels, readable in its details even when a short bar truncates text. Clicking an attempt only inspects it.
- Unknown values remain Not recorded. Do not fill historical gaps from profile files or snapshots.
- Show submitted/start/end dates and timezone, and distinguish requested frozen settings from recorded session settings. Current task fields must not be presented as historical evidence.
- Only profiles with recorded attempts have timeline lanes. Queued tasks can show their frozen settings in a separate read-only task summary.

### Defaults for new tasks

- Rename Profile settings to Defaults for new tasks and move it outside the selected-task view.
- Keep model/provider and effort controls for all ten Factory roles, including roles that have not run.
- Seed defaults from current actual profile configuration, retaining the user's Developer=medium and Orchestrator=medium selections.
- Save future Factory defaults to the Factory settings store, not shared profile files. Otherwise changing a default can still affect existing unsnapshotted work or unrelated chats.
- Use revision checks. Clearly state that editing defaults affects tasks submitted afterward only.
- Disable operational editing until dispatch snapshot enforcement is installed and verified. Do not display a working save that scheduling ignores.

### New task

Fields: title, registered project (or New project using the existing intake convention), type (feature/bug/chore), prompt, and acceptance criteria. Show the full ten-role model/provider/effort snapshot before submission. The snapshot includes optional review and repair roles without implying they will all execute.

Submit to Factory queue is the explicit action. Explain that the existing intake may start work automatically when capacity is available. No automatic submission merely from typing. Keep the prompt on validation/network failure. On success show the ticket ID and Queued state, then link the eventual root and its timeline. No decomposition toggle or arbitrary shell command field in this milestone.

Validate project selection through the existing registered-project configuration. Use existing intake rules and limits, with validation errors shown before insertion where possible. Read-only preview does not run intake, git fetch, workspace creation, or workers. Submission uses argument arrays or the existing task API, never shell interpolation.

## Immutable settings and submission protocol

An immutable snapshot contains schema version, unique snapshot ID, creation time, canonical board identity, defaults revision, and a complete role -> provider/model/effort mapping. No credentials. Role configuration and provider capability checks happen before accepting the snapshot; fail explicitly rather than substitute a model.

1. The form receives defaults and a revision.
2. Submit validates that revision and the complete request, then durably persists its immutable snapshot and submission identity before creating any dispatchable root.
3. Create one triage ticket through the existing queue adapter with that identity and snapshot reference. Persist the ticket association. A retry with the same submission identity returns the same ticket; a changed payload using that identity is rejected.
4. Intake propagates the snapshot reference when creating the root, before it can be claimed. Existing intake root idempotency remains intact.
5. All descendants and retries resolve the root's snapshot by established Factory task identity. Store snapshot reference and requested settings in attempt metadata before launching the worker.
6. Supply model, provider, and reasoning effort through existing worker launch arguments. Task-specific overrides that conflict with a frozen snapshot fail explicitly; they cannot silently defeat it.

The snapshot, not arbitrary prompt text, is authoritative. A root's reference must match the durable board/ticket/root association. Text that resembles a snapshot header inside the user's prompt cannot select another task's settings. A missing role, invalid association, missing snapshot, or unavailable configured model blocks dispatch with a clear error. Never fall back to current defaults for snapshot-managed tasks.

Creation and snapshot association must be safe across process failures: a ticket can be left queued for recovery, but a worker cannot launch before the association exists. Use durable submission identities and queue idempotency, not only disabling the browser button. If the existing ticket wrapper lacks idempotency, extend its narrow adapter using Hermes's existing idempotency support.

Factory submissions from existing chat/CLI paths must also receive a snapshot before becoming runnable. Intake-created roots carry their ticket's snapshot. Direct Factory-root creation needs the same capture before eligibility; do not claim universal immutability if only dashboard-created roots are covered. Installation verification must enumerate supported creation paths and refuse unmanaged new Factory roots rather than silently run with mutable defaults. Non-Factory tasks retain native behavior.

## Existing tasks and migration

Never rewrite historical sessions, attempts, model identities, or effort records. Completed/archived tasks remain read-only historical data.

Before enabling new-default edits, inventory existing queued/active Factory tasks. Capture a one-time legacy baseline for their future attempts using currently effective settings, including existing native overrides where supported. Label this as captured at migration, not original submission settings. Existing running workers are not restarted or modified. Conflicting per-stage overrides must remain explicit or block migration; do not flatten them into a false single-profile history.

The migration must finish or identify blocking tasks before defaults editing is enabled. This prevents a previously queued task from changing because a new-task default was edited. New snapshots are immutable; there is no edit-existing-task API in this milestone.

## Runtime integration and activation

Extend the prepared generic dispatch integration to carry effort and task-snapshot provenance, using existing Hermes launch and failure paths. Factory-specific lookup stays outside generic dispatch. Maintain compatibility for unmanaged tasks.

The old mutable task override controls are retired from the dashboard; preserve their stored values for audit, but do not silently apply them to newly frozen tasks. Existing overrides must be considered during migration.

Prepare integration changes in the isolated Hermes checkout and use disposable board/home tests before touching the installed runtime. Back up affected installed files/configuration. Inspect active workers before any necessary reload and avoid interrupting them. The user has authorized the feature; sandbox escalation may still be necessary for installed files. Do not commit, push, publish code, or launch a real paid task as a test.

## API and operational behavior

Retain loopback binding, Host/Origin checks, request token, bounded JSON bodies, and credential-free responses. Provide narrow operations for defaults, preview, submit, and submission status. All mutation routes enforce revisions or idempotency as appropriate. Reject archived-task mutations even if a client manually calls an old endpoint.

Keep source failures, submission failures, and dispatch failures distinct. If a ticket was created but the response was lost, reconcile by submission ID rather than telling the user to create another ticket. Log IDs and states rather than full prompts or configuration secrets.

## Verification and acceptance

Use disposable storage and intercepted worker launches to cover:

- Recorded model/effort remain unchanged after defaults edits; unknown history stays unknown.
- Two tasks submitted before/after an edit retain distinct complete snapshots.
- Root, late Fixer/reviewer stages, and retries all use the original snapshot, including effort.
- Creation through dashboard, existing intake, and supported direct-root paths enforces snapshots before launch.
- Duplicate submission/retry and crash recovery create one ticket/root, with matching durable associations.
- Stale defaults, missing snapshots, conflicting overrides, unknown roles, invalid projects, and foreign requests reject without launch.
- Migration preserves current queued-task behavior and leaves running workers and historical metadata untouched.
- Existing board attribution and cost semantics continue to pass.

Browser verification covers a historical task, mixed attempts, missing effort, defaults editing, New task validation, review of the frozen settings, and submitting only to a disposable queue with execution disabled. Check desktop and narrow layout, keyboard access, focus across polling, and useful save/error feedback.

Deliver updated source, integration and migration artifacts, rollback instructions, and measured validation results. Do not label requested effort as provider-observed effort; adapters may normalize it. Record limitations explicitly.

#### Scenario: A later default does not alter an existing task

- **GIVEN** task A was submitted with Developer effort medium
- **WHEN** the default changes to high and task B is submitted
- **THEN** all future stages and retries of A retain medium for Developer
- **AND** B uses high
- **AND** A's recorded run labels are unchanged

#### Scenario: A repair role starts later

- **GIVEN** a task snapshot includes Fixer before any repair stage exists
- **WHEN** review creates a repair stage after defaults change
- **THEN** Fixer launches using the task's frozen model and effort
- **AND** its actual recorded session settings appear on the timeline

#### Scenario: Submission response is lost

- **GIVEN** a snapshot and ticket were created for a submission identity
- **WHEN** the browser retries that same submission
- **THEN** it receives the original ticket
- **AND** no duplicate root or worker is created
