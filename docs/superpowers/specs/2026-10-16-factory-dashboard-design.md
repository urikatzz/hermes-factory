# Factory HTML snapshot dashboard

## Intent and approval

The user wants to see what the Hermes Factory is doing and how much its work costs, with a parent view that connects the stage cards. The user approved the HTML snapshot approach on 2026-10-16. This document defines that first version for review before implementation planning.

Success means a locally generated page can answer: which task is running or blocked, what happened across its stages and retries, which usage and costs are attributable to it, and which delivery/verification records exist. Missing evidence must remain visible as missing.

## Approach

Build a standalone Python standard-library report generator and a self-contained HTML page, with embedded styles, script, and sanitized report data. Open the file directly in a browser; no application server, build toolchain, external CDN, remote model calls, or live database mutations. Regenerating the report refreshes its data; show the generation time and source-read times.

This extends the grouping semantics of installed `factory_status.py`, without importing its command-line entry point or modifying the installed scripts. Keep report collection, domain aggregation, and HTML presentation separate. Use constructor injection for required services and small immutable records where useful; avoid a generic plugin framework.

Alternative considered: a live local server. It would reduce manual refresh and later support controls, but adds service lifecycle and API responsibilities. Deferred until the snapshot demonstrates useful and reliable attribution.

## Inputs and provenance

Accept explicit administrator-supplied paths: board SQLite database, Hermes home containing profile session databases, optional Factory published-state JSON, optional sandbox evidence root, and output HTML. Display the board/source identities; task IDs are scoped to their board and session IDs to their profile database. Do not discover or merge archived boards automatically.

The supported initial schema is the inspected Hermes revision `9e041a7428392b01b989ef9cecf46a5f96be12fc`:

- Kanban `tasks`: identity, title, status, assignee, timestamps, branch, block fields, current run and failure fields.
- `task_runs`: task/run identity, profile, status, timestamps, outcome, summary, error, metadata.
- `task_events`: task/run identity, kind, timestamp, payload.
- Profile `sessions`: session identity, model/provider, usage counters, estimated/actual cost, cost status/source.
- Optional published-state map: root task ID to recorded delivery URL.
- Optional sandbox attempt evidence: board/task/run identity, policy/images, lifecycle events and finalized cleanup/result record.

Read SQLite using read-only connections and a read transaction per database. Do not use immutable mode against active WAL databases, run migrations, enable extensions, or invoke Hermes CLI methods that could initialize or update databases. Cross-database reads are not a globally atomic snapshot; disclose that fact. A database lock or permission failure produces a clear source error. Failure to read the requested board fails generation; unavailable optional sources produce warnings and incomplete coverage.

Do not resolve paths supplied inside task text or metadata into files to read. Sandbox evidence discovery stays inside the explicitly selected evidence root and refuses symlink files. Never read credentials, session prompts/messages, raw environment variables, or project files to populate the dashboard.

## Parent task and attempt model

Recognize Factory roots using the existing exact `FACTORY:` title prefix. Attach stage tasks using the existing terminal `(t_<hex>)` root suffix, only when the referenced root exists on this board. Preserve child task IDs and every recorded task-run attempt; do not collapse repeated cards or retries into a single success. Show stage labels and cycle numbers only when recognized; otherwise retain the recorded title.

Tasks without an established root appear in an Unlinked tasks section, rather than being silently assigned to a nearby root. This includes the two independent sandbox pilot tasks. Do not invent a shared parent for that pilot. Run/session usage for those tasks is still visible.

A task's `done` status means its card completed. Verdicts such as FAIL, BLOCKED, or CHANGES_REQUIRED remain separate and prominent. A done stage with a failed verdict must never become a green successful delivery. Parent status is the recorded root status, with a separate latest verification result and delivery evidence.

## Usage and money

Use `task_runs.metadata.worker_session_id` plus the run's profile to join the correct profile session database. Inspect exact explicit metadata links only; do not use `tasks.session_id` as a worker-session fallback because it can identify the originating conversation. Do not guess using timestamps, titles, PID, or current assignee. Missing, invalid, or ambiguous links remain unattributed.

Deduplicate each `(profile database, session ID)` in totals. If a session is explicitly shared by multiple runs, show that fact; its full session usage belongs to a shared-usage group and is counted once in overall totals, not once per task or parent. Do not fabricate per-attempt allocation for a shared session.

Show recorded input, output, cache-read, cache-write, and reasoning tokens as separate counters. Do not add cached or reasoning counters to input/output to manufacture a total when semantics may overlap. Show linked-session coverage: attempts linked, attempts missing usage, and shared sessions.

Separate actual USD cost, estimated USD cost, subscription-included usage, and unknown cost. A null actual cost is unknown. A recorded zero estimate with `cost_status=included` means included usage with no dollar charge supplied; display Included / dollar amount unavailable. Never label this as free or sum unknown costs as zero. Aggregate known actual and estimated amounts separately with partial-coverage labels. This version does not fetch price lists or infer API prices for subscription usage.

Session counters describe recorded worker sessions. The dashboard does not claim to include this Codex development conversation, Docker infrastructure, idle time, subscriptions, or unlinked coordinator sessions.

## Page layout and behavior

1. Header: board name/path, snapshot time, source warnings, and local snapshot label.
2. Summary: parent task counts by status, active/blocked attempts, known actual/estimated spending, included sessions, and usage coverage.
3. Parent task list: search and status filter; rows show task name/ID, current status/blocker, stage count, retry count, duration, usage/cost coverage and delivery state.
4. Selected parent detail: ordered stage/attempt list with profile, state, verdict, timestamps, duration, model, usage/cost, error/block reason, and identifiers.
5. Timeline: recorded board transitions and optional sandbox lifecycle events in timestamp order, with source and task/run identifiers. Label these as recorded events, not a complete trace of every agent action. Break ties deterministically.
6. Artifacts/delivery: recorded manifest identity, verification outcome, branch and delivery URL, plus sandbox cleanup/result reference where matched. Missing fields say Not recorded. Recorded PR URLs are not proof of checks passing or merging.
7. Unlinked tasks and data coverage: make missing parents, failed source reads, invalid links and shared usage inspectable.

Use an accessible dark layout, readable money and token formatting, keyboard-operable controls, visible focus, and responsive stacked details on narrow screens. Embed data safely: no string concatenation into HTML for record text, no inline event handlers derived from data, and no executable contents from task summaries. Render values using text nodes. Escape JSON script delimiters; only permit HTTP/HTTPS links after URL parsing. Local paths are copyable text, not commands or automatically opened files. No external requests occur when viewing the report.

## Metrics and limits

Use all loaded recognized roots as the displayed population and show its size. Completion rate is roots in done divided by all non-archived roots, and is labelled card completion rate rather than verified delivery rate. Cycle time is median elapsed seconds from root creation to completion for completed roots with valid timestamps. Retry count is `max(0, recorded runs - 1)` per stage task, aggregated per root; separate FIX stage/cycle counts from execution retries. Do not infer missing historical attempts. Failure count refers to explicit failed run outcomes or failed stage verdicts and names that definition. Missing timestamps do not become zero-duration samples.

The report may display recorded timeout/concurrency settings when available, but does not enforce spending caps, change dispatch limits, resume workers, retry jobs, stop containers, publish code, activate the sandbox, or alter Factory workflows. Durable coordinator recovery and live controls are separate projects.

## Failure behavior

Validate required schema before querying. Unsupported board schema is a clear error, not an empty-success report. Optional missing usage columns yield incomplete usage with a warning. Treat malformed JSON metadata/events as invalid records with visible counts; never execute or evaluate it. Write the completed output atomically and leave a previous valid report untouched if generation fails. Output permissions should be owner-only because task summaries can contain private project information.

## Proposed validation for the implementation plan

Plan review will explicitly include authorization for focused automated checks and a browser inspection before completion. Coverage should include parent grouping, failed-verdict/done-card distinction, retries/cycles, explicit worker-session joins, duplicate/shared sessions, included/unknown/partial cost, locked/missing/old-schema sources, malformed payloads, safe rendering of hostile text/URLs, empty boards and small screens. Generate reports from synthetic fixtures and the existing private pilot before a read-only real-board run. Do not run new model tasks or modify live profiles to validate the dashboard.

#### Scenario: Included subscription usage

- **GIVEN** a linked session has cost_status=included, estimated cost 0 and no actual cost
- **WHEN** its task is displayed
- **THEN** the page shows Included and dollar amount unavailable
- **AND** it does not claim the task cost $0

#### Scenario: Failed stage card is done

- **GIVEN** a done stage card records VERDICT=FAIL
- **WHEN** its parent is selected
- **THEN** the card state and failed verdict are both visible
- **AND** no verified-delivery success is inferred

#### Scenario: Missing worker session link

- **GIVEN** a task run has no explicit worker_session_id
- **WHEN** usage is aggregated
- **THEN** that attempt shows Usage unavailable and reduces coverage
- **AND** no nearby session is assigned by time or title

#### Scenario: Shared session

- **GIVEN** two runs reference the same profile-scoped worker session
- **WHEN** costs and tokens are aggregated
- **THEN** overall usage counts that session once
- **AND** parent/attempt views identify shared usage without invented allocation

## Delivery and review boundary

Deliver the generator, a sample report using real private-pilot data, usage documentation, and a concrete generation command. Installation into live Hermes and automatic refresh scheduling are not part of this milestone. No commits or pushes without explicit user permission. Written-spec approval precedes the implementation plan; plan approval precedes product code.
