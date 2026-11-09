# Factory workflow templates — delivered 18 October 2026

Live dashboard: http://127.0.0.1:4611. **Workflows** manages templates; **New task** chooses a workflow and freezes workflow/provider/model/effort together. Feature, Bug fix and Chore revision 1 are seeded, with the approved stage profiles and up to three repairs. Existing tasks remain Legacy workflow and recorded attempts remain read-only.

## Validation

- 120 dashboard tests pass.
- 41 scoped Hermes integration tests pass: managed guards, creation/capture, controller, all presets, concurrent reconciliation, repair limits, model/effort launch inputs.
- 12 additional installed-release tests pass across root plus all 11 configured profile homes. Actual bundle discovery and frozen launch arguments were checked on disposable boards without starting provider workers.
- Final delivery verification: 12 controller tests pass, including retained snapshot existence after scratch cleanup.
- All 12 Hermes lint checks pass; JavaScript syntax and git diff whitespace checks pass.
- Broader native/core regression run: 88 pass, one platform skip and one known pre-existing macOS/systemd infrastructure-spawn test failure. That test expects Linux's managed-gateway placement refusal on macOS; the unchanged failure was recorded before this feature as well.
- Desktop and 390×844 browser checks cover duplicate/save revision/archive/restore/default choice, explicit selection and prompt preservation on reload, legacy history and actual-only timeline lanes. Live editor says “Workflow execution is active”; New task shows active workflow selection and the original user model/effort defaults. No production task was submitted.

The independent fresh reviewer found no Critical and seven Important issues. All seven were fixed in one regression-verified pass: retained snapshot paths, canonical plan path, completed-BLOCKED resume, unqueued retry readiness, Unity-only environment waiver, scoped preexisting evidence and persistent repair re-review context. Required source attachment paths are checked against retained completion attachment records. Intake capacity also counts controller-held active roots, including renamed roots.

## Deployment evidence

Backup: `/Users/example/.hermes/backups/factory-workflows-20261018-230002` (private, not included in public/source artifacts). The backup contains original files, coherent board/settings SQLite backups and the exact installed release manifest. 335 files were deployed, including the bundled consumer in all 12 homes. Only additive workflow/policy tables and the workflow activation flag were introduced.

There were no running Factory workers. The old Desktop backend was proven idle through its supported retirement fence, stopped normally and restarted by its supervisor (new PID 26533). Dashboard restarted on port 4611. Installed readiness reports guard version 1, workflow version 1 and all required hooks. The new-work pause was released only after activation and only because this deployment created it.

Production before/after checksums match for all tasks, runs, captured snapshots, associations, submissions and model defaults. Developer remains GPT-6 Luna / medium. No existing task graph, settings or run was migrated. No commits, pushes or paid model runs were performed.

## Decisions and practical limits

1. Keep worktrees and ledger uncommitted per the user's Git rules; review uses archives and exact patches rather than commit ranges.
2. Initialize schema explicitly to avoid a competing SQLite writer during capture; startup must perform initialization.
3. Persist the accepted active run identity in the stage registry because Hermes clears task current_run_id on completion; the claimed hook must remain installed with guards.
4. Allow task names/priorities to change while instructions/evidence stay frozen; changed scope requires a new task.
5. Refuse portable transfer for policy-managed boards because current archives omit sidecar state and scrub run identity; a future policy-aware migration is required for portability.
6. Respect explicit snapshot_attached:false for oversized archives under the existing worker contract; retain digest/reports and use full review, with no retained source archive or delta replay for that cycle.
7. Leave the pre-existing CLI-ticket kind=root provenance issue outside this change; provenance can name the intake ticket, while controller authority uses the registered actual root.
8. Raw SQLite editing and whole-board deletion remain outside supported task mutation enforcement; an administrator can remove/corrupt history through those operations.
9. Validate without paid workers as approved; provider behavior is established from captured launch arguments and contracts, not paid end-to-end execution.

Deferred minor: supported task APIs still reject archiving a delivered managed root. The root's immutable history remains available. This is separate from template archiving, which is implemented and reversible.

## Rollback

First engage the supported fleet pause and disable only new workflow capture (`WorkflowCapture.set_enabled(False)`). Keep the guard/controller installed while any managed roots/stages exist; flag-off never converts their existing snapshots to legacy. Wait for existing workers or hold their current stages before changing runtime code. Preserve all workflow tables and snapshots.

Restore original files from the private backup manifest only after managed work can remain held/enforced. If no managed roots have ever been created, the deployment's wildcard `factory-workflow/v1` required policy can be removed under a board transaction before removing its consumer. Never remove required policies for existing managed work. Do not overwrite live board/settings databases with an old backup after new tasks exist; preserve later history and roll back code/activation instead.

Source archives, exact core/dashboard patches, screenshots, verification logs, production checksums, installation scripts and hash manifests are in `artifacts/factory-workflows-2026-10-18/` in the project workspace.
