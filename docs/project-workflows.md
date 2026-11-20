# Project workflows v2

Version 2 introduces project planning above small, dependent task cycles. `execution_version: 2` is captured in immutable workflow revisions. Definitions without the field remain version 1 and continue through the original controller, including its original review/verification sequencing.

## Project planning

1. `factory-orchestrator` inspects the request/project read-only, retains `PLAN.md`, and records `project_scope` with `art`, `audio`, `ui`, and `ux` booleans.
2. Relevant `art-director` and `audio-director` stages retain their plans. They only read the request and scope, so both cards are created together and run concurrently. With no art or audio, it goes directly to architecture.
   The art director's plan needs a human decision before architecture starts. Once every director has finished, the project pauses as `blocked` with the plan's path as the reason; no retro runs and nothing is retired. Decide with `resume_factory_workflow.py --note`: a note beginning `REJECT:` returns the plan to the art director with the rest of the note as feedback, and the revised plan waits for a decision again; any other note approves that exact plan (by SHA256) and is passed to the architect. Audio-only projects have no such pause.
3. `architect` receives all those retained plans and writes the project architecture, acceptance criteria and `project-plan.json`.
4. A plan review runs before any task is written. The first code reviewer selected in the template reads the plan against the request, scope and director plans, retains `PLAN-REVIEW.md` and reports defects as findings. Blocking findings (BLOCKER, HIGH, or MEDIUM tied to an AC) return the plan to the architect; otherwise the task graph is approved.

The orchestrator's scope is not final. If the architect finds the work needs a domain the scope marks false, it sets `scope_additions`, for example `["art"]`. The scope is widened once per project and never narrowed. Added art or audio runs the missing director first and then the architect again with that plan; added UI or UX only widens the review needs.

The JSON contains `tasks`, each with `id`, `title`, `owner`, `dependencies`, `acceptance`, `needs`, and optionally `risk` (`normal` by default, or `high`). Owners are `developer`, `artist`, or `sound-designer`; `needs` uses the four scope booleans. Every project AC must be covered. IDs are unique, dependency references must exist, and cycles are refused. Code tasks integrating art/audio must depend on the corresponding asset-production tasks. There are at most 40 small tasks per project.

```json
{
  "tasks": [
    {
      "id": "sprites",
      "title": "Create the player sprite",
      "owner": "artist",
      "dependencies": [],
      "acceptance": {"AC1": "Player sprite matches the director plan"},
      "needs": {"art": true, "audio": false, "ui": false, "ux": false}
    },
    {
      "id": "integrate",
      "title": "Integrate the sprite into gameplay",
      "owner": "developer",
      "dependencies": ["sprites"],
      "acceptance": {"AC2": "Player renders and moves correctly"},
      "needs": {"art": true, "audio": false, "ui": false, "ux": true}
    }
  ]
}
```

## Task execution and repairs

Dependency-ready tasks run serially because they write into one shared project directory and each writer rebuilds one cumulative manifest. Running independent tasks concurrently would need a separate workspace and manifest per task plus a merge step; that is not implemented. Every task inherits the captured director and architecture plans, dependencies, acceptance criteria and model snapshot. Each task has separate stage keys, worker attempts, gate events and a bounded repair count; these live under the project root rather than creating independent untracked root cards.

The sequence is writer → verifier → selected review panel. Verification must explicitly PASS with complete acceptance coverage, a matching manifest, successful release audit, and no failed checks or unavailable tools. No reviewer cards are materialized before this gate passes. Unlike the legacy policy, v2 does not waive an unavailable Unity environment into a verifier pass.

Code review and security review are required. Each task gets one code reviewer: the first Claude/Codex reviewer selected in the captured template. A second selected code reviewer is a second opinion and joins only tasks the architect marked `risk: high` and final integration. UX and UI reviewers run when the task declares those needs. The art reviewer runs for tasks that need art. Audio has no specialist reviewer: the sound-designer and the verifier run the audio lint gate, and the code reviewer reads recipes and cue sheets.

Blocking findings route to the owning specialist: art-reviewer → artist, and code/security/UX/UI findings → fixer. The verifier can declare `repair_domains: ["code", "art", "audio"]` to identify asset failures. Mixed repairs run serially and finish with a cumulative implementation manifest.

Every repair restarts verification. The reviews that follow are scoped to what the repair touched: the reviewers who raised blocking findings, plus the reviewers of the repaired discipline (fixer → code and security reviewers, artist → art-reviewer, sound-designer → code reviewers). Approvals from untouched disciplines carry over within the task. Reviews that never ran stay owed: a repair after a failed first verification is still followed by the complete panel. Each gate event records `rereview` so carried approvals are visible. Final integration never carries an approval: every integration cycle runs the complete panel, including the second code reviewer, on the exact manifest that is delivered.

The captured template's repair limit applies to each task and final integration separately.

Repairing cannot fix a wrong plan, so two cases return the project to the architect instead of to a repairer or a human: a task that exhausts its repair limit, and a writer, verifier or reviewer that sets `plan_defect` to a one-sentence reason on a failing cycle. The architect receives the reason, the failing task and its findings, and may fix acceptance criteria, split tasks or add tasks and dependencies. Tasks that already passed must stay in the plan exactly as captured, and their results are kept. The revised plan is reviewed again, and revised tasks start with fresh stage keys and a fresh repair count. A project has two such replans in total, shared with plan-review revisions. After that, exhausted limits and plan defects require human review, as evidence contradictions always do. Missing tools/environment block the workflow. After explicit recovery, `resume_factory_workflow.py` requires a human note and creates fresh verification/review evidence without consuming an implementation repair cycle. It cannot waive a defect or change scope.

## Comparing director intent to the result

Asset lint remains required, but it cannot establish perceptual approval. The art reviewer retains `comparison.json`, bound to the director PLAN's SHA256 and the reviewed implementation manifest, with expected/observed criteria, outcomes and retained evidence paths.

- Art tasks start with a similarity gate. `art_similarity.py` sends each rendered asset and its style-bible reference images to the Jev model on OpenRouter (`typesafe/jev-router`, `OPENROUTER_API_KEY` in the art-reviewer profile) and retains `similarity.json` with a 0-100 score per asset. Below 80%, or with no reference image for the asset class, the reviewer stops there: the score becomes a blocking finding, the artist repairs, and no detailed comparison is spent. A missing reference is also reported as a plan defect. Only at 80% or above does the reviewer do the detailed comparison to find what is still missing. The controller requires the record, refuses an approval that contradicts a score, and treats an unavailable model as a blocked tool, never a pass. The score is a model's judgement, not a pixel measurement. Final integration is exempt: in-engine screenshots are not comparable to per-asset references.
- Art tasks require rendered asset images (`rendered_asset`); final integration requires actual in-engine images (`rendered_in_engine`).
- Audio has no perceptual comparison. The audio lint gate measures files; nobody in the workflow listens to them.
- A director mismatch requires a blocking finding and `CHANGES_REQUIRED`, which routes repair to the asset producer. Conflicting or insufficient plans require human review, not a silent change to intended style or sound.

Evidence is operator/worker-retained reporting, not an independent authentication system. The controller validates identity, shape, retention and linkage, not the truth of a subjective observation.

## Approved references and authority

A human-approved visual direction is the highest authority in a project: human-approved decisions and references > GDD > style bible and architecture > implementation plan > implementation and tests. A lower layer may refine a higher one; it may never contradict, replace, defer or silently drop it. Grey-box means gameplay scope and production-asset fidelity may be simplified; everything that is implemented follows the approved composition, palette, HUD and defining visual characteristics.

A project declares its references in `docs/references.json` (or `art/references.json`). This file and the images are human-owned and are hashed when a run starts:

```json
{"schema": "factory-references/v1", "milestone": 1, "references": [
  {"id": "look", "path": "docs/look/look.png", "roles": ["visual_reference", "immutable"], "authority": "human_approved",
   "topics": ["composition", "palette", "hud", "subjects", "materials", "lighting"],
   "approved_negations": ["no cast shadows"],
   "requirements": [{"id": "V1", "text": "Hazard-stripe trim on the door", "keywords": ["hazard stripe"]},
                    {"id": "V2", "text": "Combo readout top right", "keywords": ["combo readout"], "introduced_at": 3}],
   "deferrals": [{"requirement": "V1", "until": "milestone 6", "reason": "...", "approved_by": "human"}]}]}
```

- **Roles** are a set: `visual_reference` (how it must look), `production_asset` (may ship), `immutable` (never edited), `example` (illustration only). One file can be an immutable visual reference that is not a production asset. Without a references file, an image the GDD names as the reference image (a `docs/...png` on a line mentioning "reference", "look" or "direction") is adopted as an authoritative visual reference.
- **Scoping is a human decision.** A requirement is demanded unless a human lists it under `deferrals`, or sets `introduced_at` to a milestone later than the file's human-set `milestone` (a feature that does not exist yet). Plans, the bible and milestone names never exclude anything: wording such as grey-box, placeholder, generic, flat squares or "until milestone N" next to a requirement id or keyword, in a task that carries a requirement, or declaring the whole style deferred, is an implicit deferral and is rejected.
- **Inspection with proof.** The architect, art director, plan reviewer and art reviewer must retain `reference-inspection.json` (sha256 of the exact image, the requirement ids, one concrete observation per topic) and the controller checks the worker's own session log: a successful `vision_analyze` call on each approved reference file must exist (the art reviewer must also have opened a rendered screenshot). A well-formed JSON file without those calls is sent back. The controller refuses to create these stages for a profile whose toolsets lack `vision` (the installer adds it). The scope stage never receives reference material.
- **Traceability.** Every demanded requirement must appear in the director and architect PLAN.md and in a task's `visual` list in `project-plan.json`, and that task's acceptance must state the id. A plan that does not is corrected off the replan budget.
- **Contradictions.** A deterministic scan rejects director and architect plans, task acceptance and the style bible (`STYLE.md`, `style.json`) that forbid, defer, exclude or simplify an approved characteristic, or that use a factory mockup as the comparison target. An existing bible that does so must be amended by an artist task that carries the requirement, and is rescanned before final integration. The scan is a floor over wording: the plan reviewer must still write a "Reference audit" and report contradictions as BLOCKER findings. `approved_negations` lists characteristics that are themselves negations ("no cast shadows") so they are not mistaken for prohibitions.
- **Verification.** The art reviewer's `comparison.json` cites each approved reference by sha256, carries one criterion per demanded requirement judged on real in-engine screenshots, and a `holistic` judgement of the whole against the whole (`accept` or `reject`, a written summary, a `matches|close|differs` rating per topic, and a `HOLISTIC` criterion with the same outcome). Every requirement passing does not make a rejected whole acceptable. The similarity gate is not used and no score or pixel threshold approves anything.
- **Mockups never override.** Factory-made mockups, bibles and tiles are derived evidence. They cannot be a comparison target, cannot appear as evidence for a criterion, and cannot become authoritative unless a human edits the references file.
- **Freezing.** A change to the references file or an image mid-run (including promoting a mockup or lowering an authority) stops the project for a human, who re-approves by resuming.

## Integration and retrospective

After all tasks pass, the developer assembles the project and a final verifier-first cycle checks every project AC and the integrated visual/audio result. Only this cycle's manifest/snapshot can become the delivered project.

Integration failures have an owner. A failing acceptance criterion is attributed to the tasks that produced it, and the repair goes to those tasks' specialists: artist for an art task, sound-designer for an audio task, fixer for a code task. Reviewer findings and verifier `repair_domains` keep their normal routing. The repair card carries `repair_attribution` (AC → task IDs). The developer only assembles; it never repairs. Integration does not reopen a completed task's cycle: repairs happen in the integration cycle, and a problem that needs new or different tasks goes back to the architect as a replan.

`factory-retro` runs after a successful or unsuccessful project outcome. It writes retained `RETRO.md` with evidence, root causes, prioritized improvements, tradeoffs and validation steps. It has a scratch workspace and cannot apply improvements, modify Factory configuration, change outcomes, or publish. A missing retro report cannot silently become success.

## Installation

Use the Hermes Python environment (Python 3.11+ with PyYAML):

```sh
python scripts/install_project_workflows.py --home /path/to/.hermes \
  --preview /tmp/project-workflows-preview.json
python scripts/install_project_workflows.py --home /path/to/.hermes \
  --apply-preview /tmp/project-workflows-preview.json \
  --backup-dir /path/to/new/private/project-workflows-backup
```

The preview contains hashes and affected paths, not credentials. Apply checks it is still current, backs up replaced files and the settings database privately, installs the runtime and profile-local policy bundles, adds the retro profile/skill/model setting, and creates new active template revisions. It preserves old template revisions and task snapshots. A partial filesystem install retains `prepared.json` and its backups; `applied.json` is written only after template activation succeeds.

Restart long-running gateway/dashboard consumers after installation so their imported policy code matches the installed source. Do not remove the v2 runtime while captured v2 projects exist. To return future submissions to v1, save new template revisions with `execution_version: 1`; do not restore an old database over current snapshots. Consistent board/settings backups are required for disaster recovery.

## Tool incidents versus blocked work

A refused command is an incident, not automatically a blocked task. Workers record each one in `tool_incidents` (`command`, `reason`, `required`, `resolved`, `alternative`, `affected_criteria`). The controller blocks only on an unresolved required tool, or an unresolved incident that names an affected criterion; resolved and optional incidents continue and stay in the retained evidence. Malformed incident evidence stops the project for human review instead of being ignored. Results without `tool_incidents` keep the legacy rule: any non-empty `blocked_tools` blocks. The logic is `factory_dashboard/tool_incidents.py`, used by the handoff validator, the gate and the project controller.

## Human decisions, constraints and recovery

- **Waivers.** `resume_factory_workflow.py --decision-file` accepts `waivers` (one acceptance criterion, one path or narrow glob, optionally one reviewer, plus a reason). The finding keeps its original text in the gate record and on the waiver's audit trail; global waivers are rejected.
- **Structured constraints.** Plans may list top-level `constraints` and per-task `preserve`; a decision may add more. Kinds: `immutable` (paths), `palette` (`colors`), `layout`, `architecture`, `behavior` (`rules`) and `acceptance` (`acs`), each with an optional `paths` scope. Every task card carries them with their ids.
- **Specification conflicts.** A finding that can only be fixed by breaking a constraint is a specification conflict, not a defect. Mechanically: a finding on an immutable path. Reviewers and fixers report `spec_conflicts` (`constraint`, `reason`, `finding`). When relevant constraints exist, a read-only conflict check by a code reviewer runs before any repair is dispatched. A conflict stops the project for a human and spends no repair budget.
- **`extra_repairs`** (0 to 2, in a decision) grants that many additional repair cycles to the task in progress only.
- **Handoff recovery.** A malformed worker handoff retries only that stage, at most twice, with the exact reason, the required identity and the valid part of the previous result; retries exhausted escalates to human review. A missing or foreign run is never retried.
- **Repair budgets.** A repair that answers a genuine defect (a failed criterion or check, any finding) is a product repair and consumes the captured repair budget. A repair that answers only a verification-harness failure (`unverified:harness`) is an orchestration recovery with its own budget of 2; it can never exhaust the product budget. Every repair is recorded on the task as a charge (`work.charges`, event `project_repair_charged`); handoff retries, plan-validation retries and human resumes are logged under `orchestration_log` and charge nothing. A decision may grant `extra_repairs` (0 to 2, current task only) and set `on_exhaustion: human_review` so an exhausted task stops for a human instead of replanning.
- **Plan validation versus architectural replans.** A plan that fails structural validation (missing fields, tasks without numbered criteria, a graph that does not cover every criterion) goes back to the architect with every error and the required schema, at most twice, and spends no replan. Still invalid after that, the project stops for a human. Architectural replans (plan-review findings, plan defects, exhausted repairs) are bounded by `MAX_REPLANS`; a decision may grant `extra_replans` (one per decision) whose grant, reason and consumption are kept under `replan_grants`. A stage that finishes `BLOCKED` with `plan_defect` goes to the architect, not to a human.
- **Plan correction (separate from architectural replans).** Plan review classifies each finding (`finding_classes`) as a localized `correction` (wording, metadata, consistency) or `architectural`; unclassified means architectural, and a decision can classify the current findings by id (`plan_correction: ["F1"]`). If every blocking finding is a correction, the architect corrects the approved plan in place (at most 2 attempts per plan generation, accounted under `plan_corrections` and `orchestration_log`, never against the replan budget). The correction is checked mechanically: it must validate structurally, change no task, owner, dependency, need, risk or acceptance criterion (only `preserve` and constraints may differ), and keep every hash-like integrity baseline of the approved plan text (current values are reported beside them, never in place of them). A focused review then checks only the listed findings and the requirements they touch. A correction that changes architecture or acceptance criteria, or that fails twice, stops for a human; it never reopens the whole plan or replans on its own.
- **`--reevaluate`** re-judges existing stage evidence under the current rules without re-running stages, and also resumes a `human_review` stop.
- **Scoped secrets.** Workers never load a `.env`. A key a worker needs uses a dedicated, non-provider name (for the similarity gate, `FACTORY_SIMILARITY_API_KEY`) listed in that profile's `terminal.env_passthrough`; Hermes then supplies it from the profile's own `.env` to that profile's commands only (provider credential names such as `OPENROUTER_API_KEY` are refused by design). `scripts/factory_secrets.py doctor` checks this by name; `set` reads the value from a hidden prompt. Error text and artifacts redact the value.

## Verification

```sh
python -m unittest discover -s tests/workflow_v2 -p 'test_*.py' -v
python tests/workflow_v2/native_smoke.py
node --check runtime/factory-dashboard/factory_dashboard/assets/workflow_forms.js
```

The native smoke check needs the local Hermes source/environment. It creates a disposable board and uses synthetic handoffs; it does not call a model, run a paid task or enqueue anything on the production board.
