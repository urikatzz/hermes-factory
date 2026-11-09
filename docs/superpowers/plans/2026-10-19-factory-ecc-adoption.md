# Factory ECC Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user selects delegation. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add captured research/context guidance and a repeatable offline benchmark toolkit to Factory.

**Architecture:** A standalone standard-library Python package owns guidance transformation, benchmark fixtures, evidence validation and reporting. A migration CLI calls the existing WorkflowTemplates service with explicit revision checks. Benchmark tools prepare isolated inputs and inspect retained results without launching workers or evaluating worker-supplied commands.

**Tech Stack:** Python 3.11+, standard library, existing Factory template service and SQLite state; unittest for focused checks.

**Spec:** `docs/superpowers/specs/2026-10-19-factory-ecc-adoption-design.md`

## Global Constraints

- Preserve custom instructions, profiles, review membership, repair limits and type-default mappings.
- Existing tasks keep their captured instructions.
- Worker metadata is bounded to 3,500 characters; add no required handoff field.
- Installed StageSpec instructions allow 4,000 characters each and 20,000 combined; validate through WorkflowDefinition before any mutation.
- Use at most three search refinement rounds before assessing whether missing information prevents a correct change.
- Missing/incomplete evidence remains unknown or incomplete and cannot become a passing result.
- Show actual USD, estimates, subscription-included usage and unknown cost separately.
- The initial CLI does not launch models, execute worker-supplied commands, or enqueue production tasks.
- Keep the grader and expected outcomes outside the worker-editable fixture.
- No commits or pushes without explicit permission; no paid trials in this delivery.
- Installed files/state outside writable roots require scoped filesystem escalation.

## Review Focus

- Templates edited between preview and apply: refuse stale documents and retain already completed migration receipts; task 2 covers this.
- Guidance markers malformed, duplicated or user-edited: refuse ambiguous replacement rather than delete user text; task 1 covers this.
- Result labels claim PASS while files or manifests disagree: classify as incomplete or failed; task 4 covers this.
- Shared sessions repeat or contain conflicting accounting: deduplicate exact identities, reject conflicts, expose coverage; task 4 covers this.
- Fixture or result paths escape their intended root, or graders exceed resource limits: refuse paths and bound sandbox grading; tasks 3 and 4 cover this.

---

### Task 1: Versioned stage guidance

**Files:** Create `factory_ecc/__init__.py`, `factory_ecc/guidance.py`, `tests/ecc/test_guidance.py`.

**Interfaces:** `transform_workflow(document: dict) -> dict` returns a copied workflow document, editing only prepare/implement/repair instructions. `guidance_digest() -> str` identifies the exact guidance text. Invalid existing markers raise ValueError.

- [x] Write focused tests asserting preservation of all unrelated fields and custom text, no input mutation, exact idempotence, malformed marker rejection, and an explicit maximum of three refinement rounds.
- [x] Run `python3 -m unittest discover -s tests/ecc -p 'test_guidance.py' -v`; confirm the missing implementation fails.
- [x] Implement delimited `factory-ecc-guidance/v1` blocks. Preparation includes local search, conditional approved external research and PLAN.md evidence. All three stages include gap identification and bounded refinement without overriding the worker contract.
- [x] Run the focused tests; confirm guidance plus seeded instructions fits existing limits. Test oversized custom text through WorkflowDefinition validation in task 2.

### Task 2: Previewable, recoverable template migration

**Files:** Create `factory_ecc/migration.py`, `scripts/migrate_factory_ecc.py`, `tests/ecc/test_migration.py`.

**Interfaces:** `build_preview(templates: WorkflowTemplates) -> dict`; `apply_preview(templates: WorkflowTemplates, preview: dict, receipt_dir: Path) -> dict`. CLI takes explicit `--dashboard-source`, `--settings-db`, `--output`; apply additionally requires `--apply-preview` and `--receipt-dir`. Default operation is preview only.

- [x] Test against disposable TaskSettingsStore and real WorkflowTemplates services loaded from an explicit dashboard source: unchanged defaults/history/snapshots, archived exclusion, preserved fields, all-template size preflight, repeat no-op and stale preview rejection.
- [x] Run focused tests and observe failure before implementing migration.
- [x] Implement preview schema `factory-ecc-migration/v1` containing canonical settings DB identity, guidance digest, selected template IDs/revisions, exact before/after documents and unified instruction diffs. Target all active templates visible at preview; do not initialize production schemas.
- [x] Implement apply: verify preview identity/digest and recompute transformation; preflight every selected current template before mutation; create private per-template before/after receipts before calling `save(document, expected_revision)`. On any conflict, stop with a durable partial-progress report. Each save remains its own existing service transaction; do not claim batch atomicity.
- [x] Test a conflict occurring after the first successful save and confirm the receipt identifies precisely what changed. A fresh preview safely resumes remaining work. Never restore an old whole database as rollback.
- [x] Add logical rollback instructions: use service saves to restore the affected instructions as new revisions after checking the installed result has not subsequently changed.
- [x] Run focused tests; produce a read-only live migration preview for later activation.

### Task 3: Reproducible fixtures and trusted graders

**Files:** Create `factory_ecc/tasksets.py`, `factory_ecc/graders.py`, `benchmarks/factory-v1/taskset.json`, `benchmarks/factory-v1/cases/{bug,feature,chore}/source/`, `benchmarks/factory-v1/graders/`, `tests/ecc/test_tasksets.py`, `scripts/factory_benchmark.py`.

**Interfaces:** `load_taskset(root: Path) -> dict` validates and returns the taskset with a SHA256 content digest. `prepare_case(taskset: dict, case_id: str, output: Path) -> dict` copies only baseline source and public task instructions into a new output directory. `prepare_grading(taskset: dict, case_id: str, candidate: Path, output: Path) -> dict` creates separate candidate and trusted-grader inputs for the approved sandbox; it does not execute candidate code on the host.

- [x] Define three Python fixture tasks: fix inclusive upper-bound filtering; extend an existing formatter with an explicit option; simplify a helper while preserving behavior. Each has task type, prompt, acceptance IDs, immutable baseline files and a trusted grader with positive, boundary and negative checks.
- [x] Test missing/unknown IDs, tampered fixture digest, symlink/traversal rejection, refusal to overwrite output, and absence of hidden grader/expected answers from worker input.
- [x] Run tests to establish failure, then implement canonical taskset hashing over sorted relative paths and bytes including task instructions and grader files. Require a version change when intentionally updating fixture content.
- [x] Add CLI `taskset` and `prepare` commands and explicit grading-preparation output. Graders emit `factory-ecc-grades/v1` with case/taskset/manifest identities, grader digest and per-AC pass/fail. Document timeout and resource limits through the existing sandbox supervisor rather than host subprocess execution of candidate code.
- [x] Preserve `/private/tmp/hermes-factory-sandbox` source in `artifacts/factory-ecc-2026-10-19/sandbox-source.tar.gz`, excluding Git metadata, caches and runtime state. Record source hashes, archive hash and known pilot limitations.
- [x] Run focused fixture checks on trusted baselines/reference answers only in a disposable approved sandbox when available. If Docker is unavailable, record it explicitly and do not claim grader execution was validated.

### Task 4: Strict result import and honest reports

**Files:** Create `factory_ecc/results.py`, `factory_ecc/reporting.py`, `tests/ecc/test_results.py`, `tests/ecc/test_reporting.py`; extend `scripts/factory_benchmark.py`; create `benchmarks/factory-v1/examples/`.

**Interfaces:** `load_trials(taskset: dict, results_path: Path, evidence_root: Path) -> list[dict]`; `summarize(taskset: dict, trials: list[dict]) -> dict`; `render_markdown(report: dict) -> str`.

- [x] Define `factory-ecc-results/v1`: taskset digest; synthetic boolean; explicit variant settings (captured workflow and profile provider/model/effort); trials identified by `(variant_id, case_id, trial_id)`; task/run identities; manifest SHA256; trusted grade/gate evidence references and digests; completed/failed/infrastructure_blocked/incomplete outcome; repairs; elapsed seconds; linked usage sessions. Reject unknown schema fields, duplicate trial IDs, booleans as numbers, negative/nonfinite values and conflicting variant definitions.
- [x] Tests must reject unknown cases/taskset digest mismatches and escaping/symlinked evidence paths. Missing expected evidence yields incomplete; malformed or contradictory identities are errors. A passing card alone cannot establish benchmark success.
- [x] Implement evidence import using retained operator-selected files under evidence_root. Validate grade case/taskset/grader/manifest identity against the pinned taskset; Factory gate and trial must refer to the same manifest and real recorded runs. Acknowledge that hashes establish local integrity, not independent authenticity of operator-imported evidence.
- [x] Test first-attempt success requires completed success, zero repairs and explicit attempt evidence with no additional writer attempts. Report unknown first-attempt classification where attempt history is incomplete.
- [x] Implement variant and per-case counts: requested/imported coverage, completed/failed/blocked/incomplete, first-attempt successes with known-attempt denominator, and eventual successes with completed-plus-failed denominator. Show blocked/incomplete counts adjacent to rates and total imported count. Include repairs and elapsed duration with their known coverage. No significance or superiority claims.
- [x] Implement session deduplication by explicit session identity across all trials. Report actual USD, estimates and included usage separately, exclude estimates marked included, preserve unknown costs and identify sessions shared across variants instead of apportioning their cost. Reject conflicting records for one identity.
- [x] Add CLI `report --taskset ... --results ... --evidence-root ... --output ...`, generating private JSON and Markdown reports. Errors preserve existing outputs. Synthetic inputs force a prominent synthetic label on both formats; reject mixed synthetic/live trial sets.
- [x] Run focused tests and generate a synthetic example proving report mechanics without implying actual comparative worker results.

### Task 5: Activation, operator documentation and delivery evidence

**Files:** Create `docs/factory-ecc.md`, `docs/factory-ecc-results.md`, `artifacts/factory-ecc-2026-10-19/`; update spec status after delivery.

- [x] Document preparation, trusted grading and result import with exact CLI commands, evidence formats and scenario specifications. Explain how to select explicit variants and private boards after confirming sandbox coverage; no automated production submission or full-graph runner claim.
- [x] Document sources/attribution; if copying ECC material, preserve its MIT notice. Original adapted instructions should link the three source skills.
- [x] Run `python3 -m unittest discover -s tests/ecc -p 'test_*.py' -v`, CLI help, disposable migration end-to-end, example generation and syntax/whitespace checks. Record exact results and any environmental limitations.
- [x] Review the complete diff for scope, privacy, evidence trust and compatibility. Follow the selected execution method's review requirements; do not spawn agents without authorization.
- [x] Request scoped filesystem escalation for the concrete migration command using its reviewed preview and private receipt directory. It updates template state through existing services; no installed source patch or backend restart should be necessary.
- [x] Apply guidance and read back saved revisions. Check receipt before/after documents, unchanged default mappings and immutable historical revisions. Run apply again against a fresh no-change preview to confirm idempotence. Use disposable captures/intercepted launches for task behavior validation, not live paid tasks.
- [x] Record changed templates/revisions, rollback command/procedure, source hashes and report limitations in the delivery note. Preserve all existing project artifacts. Leave Git uncommitted and unpushed.

## Plan review and execution

Recommended method: native execution in this session. Guidance and reporting share taskset and migration contracts, and this small package does not need separate implementers. Execution and filesystem activation are complete; evidence and rollback instructions are in docs/factory-ecc-results.md.
