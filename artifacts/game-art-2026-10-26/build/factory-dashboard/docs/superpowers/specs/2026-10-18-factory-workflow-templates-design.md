# Editable Factory workflow templates

## Intent and approved direction

The user selected editable templates managed from the existing Factory dashboard, instead of a general visual workflow builder. Templates must change actual execution: participating profiles, stage order, review membership and repair limits. Existing tasks retain the workflow captured at creation, just as they retain model/provider/effort snapshots. Timelines remain read-only evidence and show only profiles with recorded attempts.

This document proposes the concrete design for review. It does not authorize Git commits, pushes, publication, or paid test tasks.

## Existing behavior and constraints

The installed orchestrator skill at `~/.hermes/factory-skills/orchestrator/software-factory/SKILL.md` defines a fixed PLAN → IMPLEMENT → parallel verification/reviews → gate graph, with up to three Fixer repair cycles. Security, UX and UI reviewers currently run on every job; the REVIEWERS header selects the code reviewers. Task Type also changes PLAN instructions, including regression evidence for bugs and no-regression criteria for chores. It does not currently choose a distinct stage graph.

The orchestrator agent creates stage cards and interprets reports. Hermes enforces dependencies but its completion/claim observer hooks run after commits and cannot veto invalid transitions. The new execution contract therefore needs synchronous guards; adding template prose alone is insufficient.

Workers depend on PLAN.md, acceptance IDs, manifest/include lists, evidence attachments and structured findings. Omitting Architect must not omit these artifacts. Local-only delivery, independent review, credential/destructive-action escalation and existing no-progress rules remain in force.

## Dashboard experience

Add a **Workflows** action beside Defaults for new tasks and New task. The editor offers a template list and a simple form, with a readable execution preview. Users can create, duplicate, rename, edit and archive templates. Saved edits create immutable revisions; templates referenced by tasks cannot be hard-deleted.

Editable fields:

- Name, description and default task type: feature, bug or chore.
- Preparation stage profile and instructions.
- Implementation profile and instructions.
- Review panel: chosen supported reviewer profiles, with per-reviewer focus notes.
- Independent verifier profile and additional verification instructions.
- Repair profile, repair instructions and maximum repair cycles, from zero to three.

V1 uses a fixed set of stage kinds with editable membership and instructions: prepare, implement, review, verify and repair. Preparation and implementation are sequential; selected reviewers and verification can run in parallel after implementation. Arbitrary graph edges, custom scripts, expression conditions and nested subworkflows are excluded. This keeps template validity understandable without creating a second programming language.

Only profiles advertising the relevant stage capability may be selected. Seed capabilities follow existing worker contracts: Architect prepares; Developer prepares/implements; Fixer diagnoses/prepares/repairs/implements; supported review profiles review; Verifier verifies. These capabilities describe output contracts and workspace permissions, not model choice. Models and effort continue to come from the separately captured profile settings.

Every template requires preparation, implementation, at least one code reviewer, and independent verification. A writer cannot review or verify its own work. Selecting reviewers is explicit; no invisible classifier silently adds or skips specialists. Missing profile configuration, unsupported capabilities, duplicate reviewer entries or invalid limits prevent saving with a field-specific explanation.

## Initial presets

| Template | Preparation | Implementation | Selected reviewers | Verification | Repair |
|---|---|---|---|---|---|
| Feature | Architect: design and acceptance plan | Developer | Claude, Security, UX, UI | Verifier | Fixer, up to 3 cycles |
| Bug fix | Fixer: diagnosis, root cause and regression plan | Fixer | Claude, Security | Verifier | Fixer, up to 3 cycles |
| Chore | Developer: scope and no-regression plan | Developer | Claude | Verifier | Fixer, up to 3 cycles |

Codex Reviewer can be added to any panel. UX/UI can be enabled for a bug with a user-facing surface. These are editable starting presets, not automatic risk judgments. Preparation always produces the acceptance plan and manifest contract required downstream, even when Architect does not run.

## New-task selection and immutable history

Task Type chooses the default template. The New task form shows the selected template and revision, stage/profile sequence, reviewer panel, repair limit and full provider/model/effort review. The user may select another active template before submission. Changing Type updates the suggested template only until the user explicitly chooses one; subsequent changes retain that choice and show any type/template mismatch as information.

Submission validates both defaults revision and workflow revision. If either changed, require a refreshed preview while preserving the prompt. The durable submission captures the entire workflow definition and the complete role settings together before ticket creation. A later rename, edit, archive or default change cannot affect this submission, its intake root, new stages, retries or repairs. Duplicate/recovered submission IDs retain both original snapshots.

CLI/chat tickets and direct roots also capture a template before eligibility. Use structured intake metadata for an explicit selection, or the configured default for the task type. Preserve existing v1 intake compatibility through its established parser. No prompt-body header is authoritative for workflow identity. Selection requires a validated template ID/revision; unknown explicit selections fail clearly rather than choosing a different workflow.

Existing tasks without a workflow snapshot keep legacy execution. Do not infer their workflow from current templates or rewrite their past graph. The dashboard labels them **Legacy workflow**. Existing immutable model/effort snapshots remain valid.

## Execution ownership and enforcement

A focused Factory workflow controller owns stage creation, stable stage identity, dependencies, cycle state and root completion for managed roots. The orchestrator remains the user-facing coordinator and can explain/escalate outcomes, but cannot invent a different graph for a managed task. Its skill and role instructions distinguish managed templates from legacy roots.

Keep Factory policy in the plugin. Extend Hermes only with narrowly scoped synchronous transactional mutation guards where existing hooks cannot enforce the contract. Guards must cover every supported route to stage creation/claim, changes to assignment or dependencies, and completion/reopening; CLI, tools and web APIs must converge on them. Post-commit observers trigger reconciliation, and normal dispatch ticks recover missed notifications.

Persist controller state and logical stage/run associations in additive plugin-owned board tables so stage transitions and board mutations can commit atomically. Immutable workflow definitions remain in the Factory sidecar, associated before the root becomes eligible. Use the board write lock and unique `(root, stage-key, cycle)` identities for reconciliation. Callbacks do not perform network calls or launch workers while holding the lock. Read-only inspection and rejected mutations remain auditable.

The controller materializes only the next eligible phase. Every stage inherits the root's frozen workflow and profile settings. A stage claim checks its logical identity, profile, predecessor outcomes and cycle. A removed dependency, manually completed card, title change, forged body or arbitrary extra stage cannot bypass those checks. Native tasks and legacy Factory roots retain their current behavior.

A terminal card status is not sufficient evidence of passing. Normalize supported worker handoffs against an explicit result schema, expected stage/run identity, acceptance coverage and the same code manifest. Unknown/missing verdicts or contradictory artifacts block progression with an actionable reason. Failed/crashed attempts are infrastructure/worker failures handled through existing bounded retry policy; they do not count as a completed repair cycle and cannot allow delivery.

The gate follows existing severity and no-progress policy. All selected reviewers and Verifier must finish for the same implementation manifest before judging a cycle. On fixable failure, create one repair stage, then rerun the entire selected panel and verification against its resulting manifest. Count a repair cycle once, durably. Zero allowed cycles escalates after the first failed gate. Exhausting the limit, unfixable repeat findings, missing capabilities or environment evidence leads to human review; never an endless repair loop.

Root success is allowed only after the current gate passes and required stages have real run evidence. Human intervention can resume the frozen workflow with an explicit recorded decision; it does not silently replace its template or remove required stages. Extending limits or replacing a workflow on an existing task is outside v1; submit a new task when a different workflow is required.

## API and storage

Versioned template operations use the existing loopback Host/Origin/token protections and revision conflict responses. Separate template definitions, per-type default mappings and immutable per-submission snapshots. Reject unknown fields and bound instruction sizes. Stored template instructions are task instructions, never executable shell/config fragments. No credentials are returned.

Expose list/get/create/save/archive operations, type-default selection, and a side-effect-free workflow preview. Report responses expose captured workflow name/revision, planned sequence and current phase separately from recorded timeline lanes. Future/skipped stages appear in a compact workflow summary, never as fabricated agent runs.

Archiving a template removes it from new-task selection. A type-default template cannot be archived until its replacement is chosen. Historical tasks continue displaying the captured name and definition even if the original template is renamed or archived.

## Validation and rollout

Use disposable homes/boards and intercepted launches. Cover:

- Different presets produce the intended profiles and dependencies, including Fixer diagnosis/repair.
- Missing preparation artifacts block implementation; missing reviewer/verifier evidence blocks delivery.
- Writer/reviewer independence, explicit optional specialists and capability validation.
- Duplicate/out-of-order notifications, concurrent reconciliations, nested transaction rollback and restart recovery.
- Native/legacy isolation; fake task headers; unsupported profile/extra stage; direct CLI/API mutation attempts.
- Every failure path, same-manifest review, zero/maximum cycles, no-progress escalation and bounded worker retries.
- Template/default edits after submission do not alter old roots, late stages or retries.
- Lost responses, stale form revisions and archived template selection preserve user input and original submission identity.
- Dashboard keyboard/mobile behavior; only actual attempts appear on the timeline.

Deployment is gated: prepare source and backups, inspect active work, pause new claims without killing workers, install guards/controller and updated worker contracts, verify discovery and launch inputs on a disposable board, seed templates/default mappings, then enable new submissions. Existing legacy tasks are not converted. Rollback disables new template submissions first, preserves snapshot/controller state, and keeps managed tasks held or enforced until they cannot fall back to prompt-only execution.

## Alternatives considered

1. **Prompt-only templates:** smallest change, but agents could skip reviewers, change stages or ignore limits. Rejected because the dashboard would not reliably control execution.
2. **Validated templates with a deterministic controller (selected):** more integration work, but bounded complexity, enforceable transitions and recoverable state.
3. **General graph editor:** maximum flexibility, with substantially higher validation, migration and debugging cost. Deferred.

## Self-review

The design preserves current acceptance/manifest contracts, separates legacy and managed behavior, identifies transactional guard gaps, and defines optional review selection without guessing applicability. Models/effort and workflows freeze together; repair cycles and worker retry semantics are distinct. No unresolved placeholders. Implementation must verify all mutation routes before enabling managed workflow submissions.
