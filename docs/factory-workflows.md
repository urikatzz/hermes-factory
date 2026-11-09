# Factory workflow templates

Use **Workflows** to duplicate or edit Feature, Bug fix and Chore templates. Choose preparation/implementation profiles, reviewers, instructions and zero to three repair cycles. Verification and at least one code reviewer are mandatory. **Use as type default** changes the suggestion for future tasks.

**New task** shows the selected workflow and profile settings before submission. An explicit workflow choice survives type changes and reloads. Reloading adopts the latest revision but preserves the prompt. Saved tasks retain their complete workflow and model/effort snapshot; later changes apply only to new tasks.

The task's **Captured workflow** summary lists planned stages. Timeline bars are recorded attempts only. A repair adds a Fixer attempt followed by the full selected review panel.

#### Scenario: Edit a template after a task starts

- **GIVEN** a task captured Feature revision 1
- **WHEN** Feature revision 2 is saved
- **THEN** the existing task and all its retries retain revision 1
- **AND** future tasks may capture revision 2

#### Scenario: Review finds a blocking defect

- **GIVEN** all selected readers reviewed the writer's exact manifest
- **WHEN** blocking evidence remains and the repair limit permits another cycle
- **THEN** one repair stage receives the reviewed baseline and findings
- **AND** every selected reviewer and verifier runs again afterward

#### Scenario: A worker cannot run

- **GIVEN** a current stage blocks because the environment needs intervention
- **WHEN** a human restores the environment and explicitly resumes it
- **THEN** the same captured settings and repair limit remain enforced
- **AND** the decision is recorded in workflow history

For infrastructure-blocked stages, use `scripts/resume_factory_workflow.py --help` from the owning Hermes home. It requires an explicit root and recovery note. Human-review decisions, exhausted repairs, or changed scope require a new task; no command silently waives evidence.

Activation requires the actual Factory consumer and all creation, mutation, model-resolution and reconciliation hooks. An unavailable runtime disables new submissions. Existing legacy tasks keep their original workflow.

Managed-board portable export is refused because current archives omit required sidecar state. Back up the board and task-settings SQLite databases consistently together. Disable new workflow intake before rollback; retain the guard/controller while managed work exists. Never remove policy state to bypass a blocked task.
