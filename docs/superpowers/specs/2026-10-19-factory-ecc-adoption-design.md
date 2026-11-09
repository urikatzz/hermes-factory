# Selective ECC adoption for Factory

Status: approved and delivered 19 October 2026. See `docs/factory-ecc-results.md` for activation, evidence and limitations.

## Intent and scope

The user approved selectively adopting ECC after a repository review. The first delivery adds search-first preparation, bounded context retrieval and a small repeatable Factory benchmark. Success means workers receive useful repository evidence before implementation and operators can compare explicitly selected model/effort/workflow variants with honest quality, duration and usage measurements.

Continuous learning remains a later delivery, after evaluation exists. This delivery adds no automatic instruction promotion, ECC installation, replacement controller or new production task submissions.

## Existing integration points

- Installed worker contract: `/Users/example/.hermes/factory-skills/worker/factory-worker/SKILL.md`. Preparation is read-only, produces retained PLAN.md and an include list, and downstream readers use the exact manifest snapshot. Worker metadata is bounded to 3,500 characters.
- Workflow definitions: `/Users/example/.hermes/factory-dashboard/factory_dashboard/workflow_templates.py`. Existing services support immutable template revisions and stage instructions. Editing preset source alone does not update already seeded templates.
- Existing templates capture preparation, implementation, review, verification and repair instructions per task. The controller owns progression and review gates.
- Sandbox source currently exists at `/private/tmp/hermes-factory-sandbox`; its `scripts/run_pilot.py` demonstrates private-board worker execution. It is a narrow IMPLEMENT/VERIFY pilot, not evidence that the full managed graph is sandboxed. Preserve a source copy in the project before depending on this temporary directory.
- The workspace currently contains untracked delivery artifacts and documentation. Preserve them and do not commit or push without permission.

## Approaches

1. Adapt guidance into captured stage instructions and add an offline benchmark report CLI. Small runtime surface, uses existing immutable revision behavior, and introduces no always-running service. Selected.
2. Install ECC's Hermes adapter and connect its evaluation utilities. Broader skill coverage, but overlapping worker rules and harness-specific behavior require more integration and maintenance. Its candidate execution gate currently refuses execution because containment is unimplemented; it cannot replace the Factory sandbox.

## Search-first preparation

Append a clearly delimited, versioned guidance section through the workflow template service to preparation instructions. Preserve custom instructions, profiles, review membership, repair limits and type-default mappings. Detect the same guidance revision so installation is idempotent. Use optimistic revision checks; conflicting edits require a fresh read rather than overwrite.

Preparation first searches the assigned repository for existing implementations, conventions and extension points. Where a dependency or integration is relevant, consult available approved documentation or registries. External searches are conditional on available tools and sandbox policy; do not introduce web tools or broaden network access. Missing channels are reported as unavailable, never as evidence that no solution exists.

PLAN.md records the need, inspected paths, existing solutions, alternatives where an architecture choice matters, the selected approach and reasons, and remaining context gaps. Existing constraints on credentials, source access, Git operations and authored references remain authoritative. Guidance must fit the current instruction size limits.

## Bounded context retrieval

Add guidance to preparation, implementation and repair instructions. Start with repository terminology and likely entry points, inspect relevant callers and tests, name any remaining gaps, then refine the search. Use at most three search refinement rounds before assessing whether missing information prevents a correct change. The round limit does not prohibit necessary code reading or justify guessing requirements.

Preparation puts concise paths and reasons in PLAN.md. Implementation checks those references against its assigned workspace. Reviewers continue to inspect only their manifest snapshot and permitted parent artifacts. Detailed evidence stays in existing retained reports; do not grow handoff metadata beyond the current bound or add an unrecognized required handoff field.

New tasks capture the revised stage instructions. Existing tasks keep their captured instructions. Avoid changing the global preloaded worker contract to inject these new behaviors into active tasks.

## Benchmark definition

Add a standalone standard-library Python package and CLI under this project, with versioned JSON definitions and deterministic local graders. Keep report calculation separate from file loading and command-line presentation. Do not add a dashboard endpoint or alter production storage schemas for the first delivery.

Provide three small offline fixture tasks: a bug fix, extension of existing functionality, and a behavior-preserving chore. Each contains a source baseline, task prompt, acceptance IDs, expected behavior and trusted grader definition. Keep the grader and expected outcomes outside the worker-editable fixture. Fixture changes create a new taskset version/digest.

The initial CLI prepares explicit benchmark inputs and reports imported results. It does not launch models, execute worker-supplied commands, or enqueue production tasks. Document how to run selected cases on a disposable board through the existing Factory/sandbox path after confirming the chosen profiles' runtime coverage. Do not describe the two-stage pilot as a full Factory benchmark runner.

Each imported result identifies taskset digest, case, trial, variant, captured workflow/model/effort settings, task/run identities, reviewed manifest, deterministic acceptance outcomes, terminal outcome, repair count, elapsed duration and evidence paths. Variants are explicit; never infer them from current defaults. Reject duplicate trial identities, unknown cases, mismatched taskset versions and malformed records. Missing/incomplete evidence remains unknown or incomplete and cannot become a passing result.

Report per-case coverage and variant totals, first-attempt success, eventual success, repairs and duration. First-attempt success requires a passing completed task with zero repair cycles and recorded attempt evidence. Benchmark success requires trusted acceptance results and Factory gate evidence for the same manifest. Infrastructure-blocked and incomplete trials are shown separately; include their counts and the explicit denominator beside success rates. Do not claim statistical superiority from a small sample.

Show actual USD, estimates, subscription-included usage and unknown cost separately, following the existing dashboard accounting rules. Deduplicate explicitly linked shared sessions; do not sum overlapping sessions or invent a complete cost from partial records. Offline synthetic examples are visibly labeled and are never represented as model evaluation results.

## Delivery and validation

1. Prepare source and guidance changes in this writable project or an existing isolated checkout. Preserve the temporary sandbox source needed for reproducibility.
2. Add scenario documentation and focused checks for revision preservation/idempotence, retrieval bounds, result validation, manifest identity, duplicate trials, incomplete evidence and cost accounting. Run focused checks before completion; no paid model calls are needed to validate reporting mechanics.
3. Produce a dry-run migration preview listing target templates and exact instruction changes. Back up only affected installed files and template definitions before activation; installation outside writable roots requires the normal scoped filesystem approval.
4. Activate guidance for new submissions through the existing template service, preserving captured tasks. Verify installed revisions and discovery with disposable state and intercepted worker launches.
5. Deliver source, commands, migration evidence, offline example reports and explicit limitations. Actual comparative model results require subsequent benchmark execution; do not fabricate them.

## Scenarios

#### Scenario: An implementation already exists

- **GIVEN** a task requests functionality present in the repository
- **WHEN** preparation searches the assigned source
- **THEN** PLAN.md identifies the existing implementation and relevant extension point
- **AND** explains why reuse or a change is appropriate.

#### Scenario: External research is unavailable

- **GIVEN** a worker has repository access but no approved external search channel
- **WHEN** preparation evaluates a dependency choice
- **THEN** it records the unavailable channel and available local evidence
- **AND** does not broaden sandbox access or invent external findings.

#### Scenario: Guidance changes during an active task

- **GIVEN** task A captured a previous workflow revision
- **WHEN** the guidance migration saves a new revision
- **THEN** task A and its repairs keep their captured instructions
- **AND** subsequent submissions can capture the new revision.

#### Scenario: Benchmark evidence is incomplete

- **GIVEN** a completed card lacks matching acceptance or gate evidence
- **WHEN** a benchmark report imports the trial
- **THEN** it reports incomplete evidence
- **AND** does not count the trial as a success or assign missing cost a zero value.

#### Scenario: Migration runs twice

- **GIVEN** a template already contains the selected guidance version
- **WHEN** installation is repeated
- **THEN** no duplicate instruction block or unnecessary template revision is created.

## Deferred

Automatic learning, full managed-graph sandbox benchmarking, automated paid trial scheduling, model selection, statistical promotion gates, dashboard benchmarking UI and instruction-library snapshots beyond captured stage text are separate changes.

## References

- https://github.com/affaan-m/ECC/blob/main/skills/search-first/SKILL.md
- https://github.com/affaan-m/ECC/blob/main/skills/iterative-retrieval/SKILL.md
- https://github.com/affaan-m/ECC/blob/main/skills/eval-harness/SKILL.md

Adapt concepts to Factory contracts. If implementation copies ECC text or code, retain the applicable MIT license and attribution alongside it.
