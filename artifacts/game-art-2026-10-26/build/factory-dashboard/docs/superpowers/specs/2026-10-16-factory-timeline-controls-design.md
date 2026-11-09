# Factory timeline and model controls

## Intent and agreed behavior

Extend the Hermes Factory dashboard with the readable agent timeline shown in the user's Super Simple Software Factory reference. The user wants saved model defaults for each agent and a task-wide model override applying to every agent in that task. Clearing the override restores each agent's default. Changes affect future attempts; running and completed attempts retain their recorded model.

This is the proposed architectural design for review, not authorization to activate live changes. The existing snapshot design remains the authority for attribution, cost semantics, source handling, and historical evidence. No commits or pushes without explicit permission.

## Approach and alternatives

Recommended: add a local live dashboard around the existing Python collector and aggregation code, with a narrow configuration API and a dispatch integration that resolves the model for each new attempt. Reuse the snapshot exporter and domain calculations. Keep presentation, model-selection policy, persistence, and Hermes integration separate. Use existing Hermes configuration and dispatch conventions rather than introducing another scheduler.

Alternative: restyle the standalone HTML snapshot with the same timeline. This has fewer dependencies and remains simple to distribute, but cannot persist operational model selections or update live without regeneration. It does not fully satisfy the requested controls.

The existing implementation is in `/private/tmp/hermes-factory-dashboard`; this workspace currently contains copied documentation and generated reports. Implementation planning must establish the source worktree and inspect the installed Hermes configuration/dispatch interfaces before naming integration files or choosing a persistence mechanism. The previous sandbox investigation identifies `hermes_cli/kanban_db_dispatch.py::_default_spawn` as the worker launch boundary; its current behavior must be checked before modifying it.

## Screen design

Keep a searchable task list and open a selected Factory parent into the timeline. Place task status, elapsed time, recorded costs, token counts, and coverage above it. The task-wide model selector sits in this header and offers a clear reset to agent defaults.

Use a fixed left column for agent role, model default, and effective selection. The horizontal area shows actual execution intervals on a shared time axis. Assign stable colors to roles and use text/icons as well as color for state. Separate human events and deterministic checks into their own lanes when recorded evidence supports them. Represent retries as distinct attempt bars; do not combine them into one successful stage. Concurrent attempts must remain separately selectable.

Selecting a bar opens attempt details: role/profile, actual model/provider, start/end, status, verdict, usage/cost coverage, errors, and available delivery evidence. Historical bars show the model actually used even after defaults change. A lane can therefore contain attempts using different models.

Queued work appears separately from measured execution. Missing timestamps do not become fabricated durations. Running intervals grow with elapsed time but are labeled ongoing. Provide horizontal scrolling with readable labels and a stacked view on narrow screens. Controls support keyboard operation and visible focus.

## Model-selection rules

Saved defaults are scoped to the selected Factory configuration and agent role. Task overrides are scoped by board identity and Factory parent task ID; they apply to all agent roles executing stages under that parent. They do not mutate shared profile configuration to temporarily switch one task's model.

Resolution for a new attempt is: task-wide override when present, otherwise the saved agent default. Existing configured agent models initialize the defaults; missing required model configuration produces an actionable configuration error. Provider and model identity travel together. This milestone changes model selection only, retaining existing reasoning and tool settings subject to model compatibility validation.

The UI distinguishes the saved role default, a task override, and the effective selection. Editing a role default while an override exists updates the saved default but leaves that task's effective selection unchanged. Resetting the override makes each role inherit its current default.

At dispatch, resolve and capture the effective selection once for that attempt. Persist its source and configuration revision alongside execution metadata using the supported Hermes integration. A later edit cannot change an already dispatched worker. A retry is a new attempt and resolves the then-current configuration. Failed dispatches remain recorded failures; the system must not silently substitute another model.

## Data and service boundaries

The existing collector continues to read selected board/profile sources and build report data. A local server exposes the report to the browser; polling refreshes observations without launching work. Preserve selection and an open detail panel across refreshes. Show last successful refresh time and source errors instead of presenting stale information as current.

A model-selection service owns precedence and compatibility rules. A persistence adapter reads/writes the supported configuration store. A dispatch adapter supplies the captured effective selection to the existing worker launcher. Constructor injection supplies required dependencies. The browser never writes database files or edits profiles directly.

Model choices come from supported configured providers/models. Validate selection and required configuration before saving, without paid model calls. Clearly surface runtime provider failures. Configuration edits use revisions to reject stale updates from another tab and return the current state for review. A failed save preserves the prior configuration and remains visibly unsaved in the UI.

Bind the service to loopback and restrict configuration writes to the local application through origin/request validation. Do not expose provider credentials in API responses. Implement narrow configuration mutations, not a generic command-execution endpoint.

## Evidence and scope

Preserve explicit worker-session joins, shared-session deduplication, separate actual/estimated/included/unknown costs, and the distinction between a completed card and a passing verdict. Configured future models are not evidence of the model used by a historical attempt.

Use available recorded events only. Context-window occupancy, tool-call activity marks, structured handoff inspection, and detailed gate results can be added when reliable source records exist. They are not simulated in this milestone. Automatic retry controls, workflow editing, spending enforcement, and scheduler replacement are outside this design.

The reference offers useful visual patterns but has a different schema and runtime. Adapt its interaction and styling concepts to Hermes; preserve its MIT notice if copying substantial code. References:

- https://github.com/disler/super-simple-software-factory
- https://github.com/disler/super-simple-software-factory/blob/main/.claude/skills/sssf/apps/visualizer/src/components/SessionTrace.vue
- https://github.com/disler/super-simple-software-factory/blob/main/LICENSE

## Validation and delivery

Use fixtures and a disposable dispatch integration to verify precedence, persistence, revision conflicts, concurrent tasks, captured model identity, and failure behavior. No paid model runs are needed to verify selection routing. Retain existing dashboard attribution checks. Inspect the timeline in a browser at desktop and narrow widths, including scrolling, attempt selection, refresh continuity, keyboard navigation, and failed saves. Report any unavailable browser verification explicitly.

Deliver the live dashboard source, integration instructions, a sample timeline, configuration behavior documentation, and test evidence. Prepare activation steps separately after the integration is concrete; do not change installed profiles or live scheduling merely to demonstrate the UI.

#### Scenario: Task override applies to every agent

- **GIVEN** planner and builder have different saved defaults
- **WHEN** a model override is saved for their parent task
- **THEN** subsequent attempts by both roles use the override
- **AND** other tasks continue to use their own effective selections

#### Scenario: Reset restores individual defaults

- **GIVEN** a task has a model override
- **WHEN** the user resets it to agent defaults
- **THEN** each future attempt resolves its role's current saved default
- **AND** recorded historical models remain unchanged

#### Scenario: Editing during execution

- **GIVEN** an attempt has already captured its model at dispatch
- **WHEN** its task override or agent default changes
- **THEN** that attempt retains its captured model
- **AND** a later attempt resolves the new effective selection

#### Scenario: Concurrent configuration edits

- **GIVEN** two browser tabs loaded the same configuration revision
- **WHEN** one saves and the other submits an edit based on the old revision
- **THEN** the second save reports a conflict without overwriting the first
- **AND** the current configuration is available for review

#### Scenario: Incomplete historical evidence

- **GIVEN** an attempt has no recorded model or end timestamp
- **WHEN** its details are displayed
- **THEN** missing values remain explicitly unavailable
- **AND** current configuration does not fill historical evidence gaps
