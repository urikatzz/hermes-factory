# Project workflows v2

Version 2 introduces project planning above small, dependent task cycles. `execution_version: 2` is captured in immutable workflow revisions. Definitions without the field remain version 1 and continue through the original controller, including its original review/verification sequencing.

## Project planning

1. `factory-orchestrator` inspects the request/project read-only, retains `PLAN.md`, and records `project_scope` with `art`, `audio`, `ui`, and `ux` booleans.
2. Relevant `art-director` and `audio-director` stages retain their plans. They only read the request and scope, so both cards are created together and run concurrently. With no art or audio, it goes directly to architecture.
   The art director's plan needs a human decision before architecture starts. Once every director has finished, the project pauses as `blocked` with the plan's path as the reason; no retro runs and nothing is retired. Decide with `resume_factory_workflow.py --note`: a note beginning `REJECT:` returns the plan to the art director with the rest of the note as feedback, and the revised plan waits for a decision again; only the exact phrase `APPROVE <root id> <first 12 hex of the plan SHA256> <first 12 hex of the references digest, or none>` (optionally followed by a comment) approves that exact plan and is passed to the architect; the stop message prints the phrase. Any other note, including a recovery note, is refused and approves nothing. A recovery after the approved references changed needs `APPROVE-REFERENCES <first 12 hex of the new digest>` in the note; recovery alone never re-approves them. Audio-only projects have no such pause.
3. `architect` receives all those retained plans and writes the project architecture, acceptance criteria and `project-plan.json`.
4. There is no independent plan review: a structurally valid plan goes straight to task execution (`PLAN_REVIEW_ENABLED = False` in `project_controller.py`; the `project_plan_approved` event records `review: disabled`). The deterministic approved-reference scan at plan capture still rejects plans that forbid, defer or weaken an approved requirement. The reviewer stage, its findings and plan correction are kept behind that switch for projects already mid-flight and can be restored by setting it to `True`: a code reviewer then reads the plan, retains `PLAN-REVIEW.md`, and blocking findings (BLOCKER, HIGH, or MEDIUM tied to an AC) return the plan to the architect.

The orchestrator's scope is not final. If the architect finds the work needs a domain the scope marks false, it sets `scope_additions`, for example `["art"]`. The scope is widened once per project and never narrowed. Added art or audio runs the missing director first and then the architect again with that plan; added UI or UX only widens the review needs.

The JSON contains `tasks`, each with `id`, `title`, `owner`, `dependencies`, `acceptance`, `needs`, and optionally `risk` (`normal` by default, or `high`). Owners are `developer`, `artist`, or `sound-designer`; `needs` uses the four scope booleans. Only structure is enforced: IDs are unique, dependency references must exist, and cycles are refused. Code tasks integrating art/audio must depend on the corresponding asset-production tasks. There are at most 40 small tasks per project.

Wording, length and coverage are not validation errors; the architect learns them from the `task-writing` worker skill (`runtime/factory-skills/worker/task-writing`), which its card tells it to load. A project AC that no task states is not forgotten: the controller records it (`uncovered_acs`, event `plan_uncovered_acs`), the plan-review card lists it when that stage is enabled, and the final integration task always states each one as an explicit "not stated by any planned task" criterion with its text from `PLAN.md`.

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

A task that exhausts its repair limit stops for a human; it never goes back to the architect. The stop names the task, the unresolved findings and the options: resume with `extra_repairs` (1 to 2) and, to try a stronger model, `model_overrides` (`{"fixer": {"provider": "...", "model": "...", "effort": "high"}}`), or change the plan in a new task. A worker that thinks the plan or an acceptance criterion is wrong finishes `VERDICT=BLOCKED` with a reason, and that also stops for a human; `plan_defect` is no longer a routing signal. Missing tools/environment block the workflow. After explicit recovery, `resume_factory_workflow.py` requires a human note and creates fresh verification/review evidence without consuming an implementation repair cycle. It cannot waive a defect or change scope.

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
- **Role-specific, image-grounded findings.** A successful vision call is necessary, not sufficient. Every observation carries a `region` (a normalised box on the image); observations must be distinct and span several cells of a 3x3 grid. Each role also writes `role_findings`, one per demanded requirement, with its own region: the art director says how the requirement is reproduced and whether by `generated`, `procedural` or `hybrid` production; the architect names the task that carries it; the plan reviewer rates it `faithful`, `weakened` or `missing` against the image (the last two need a blocking finding naming it); the art reviewer rates it `matches` or `differs` for a retained rendered screenshot (a `differs` needs a blocking finding and `CHANGES_REQUIRED`). Restating the requirement text, repeating a finding or reusing a region is refused. These checks raise the cost of generic filler and force a look across the whole image; they cannot prove the content is true, which is why the holistic judgement and the human gate remain.
- **Art plan gate.** With approved references the art plan needs a heading for how the direction is achieved, the production assets, generation versus procedural work, articulation and animation, environment/lighting/interface implementation, how rendered results are compared with the reference, and the requirements active per milestone, plus one representative mockup retained as `plan-mockup.png` (a real PNG of at least 640x360 that the director opened with `vision_analyze`). The mockup is subordinate to the reference. The human gate shows its path and the project waits for approval.
- **Traceability.** Every demanded requirement must appear in the director and architect PLAN.md and in a task's `visual` list in `project-plan.json`, and that task's acceptance must state the id. A plan that does not is corrected off the replan budget.
- **Contradictions.** A deterministic scan rejects director and architect plans, task acceptance and the style bible (`STYLE.md`, `style.json`) that forbid, defer, exclude or simplify an approved characteristic, or that use a factory mockup as the comparison target. An existing bible that does so must be amended by an artist task that carries the requirement, and is rescanned before final integration. The scan is a floor over wording, not a verdict. Findings in **operative rules** (style bible, `style.json`, task acceptance) are hard: they cannot be explained away, so the original grey-box rules can never be accepted while they stand. Findings in **plan prose** (director and architect `PLAN.md`) may be reworded or explained in a top-level `scan_explanations` list (a quote of at least 15 characters, the requirement id, an explanation of at least 40 characters). An explained candidate is not dismissed: it appears in the human approval record, and the plan reviewer must rule on each in `scan-adjudication.json` (`contradiction`, `benign` or `ambiguous`, quoting the text, with a rationale). A contradiction needs a blocking finding and returns the plan; an ambiguous one stops for a human, who accepts it with `SCAN-BENIGN <id>` in the resume note. Scan rejections have their own retry budget (3), separate from the 2 retries for malformed handoffs. The plan reviewer must still write a "Reference audit" and report contradictions as BLOCKER findings. `approved_negations` lists characteristics that are themselves negations ("no cast shadows") so they are not mistaken for prohibitions.
- **Verification.** The art reviewer's `comparison.json` cites each approved reference by sha256, carries one criterion per demanded requirement judged on real in-engine screenshots, and a `holistic` judgement of the whole against the whole (`accept` or `reject`, a written summary, a `matches|close|differs` rating per topic, and a `HOLISTIC` criterion with the same outcome). Every requirement passing does not make a rejected whole acceptable. The similarity gate is not used and no score or pixel threshold approves anything.
- **Mockups never override.** Factory-made mockups, bibles and tiles are derived evidence. They cannot be a comparison target, cannot appear as evidence for a criterion, and cannot become authoritative unless a human edits the references file.
- **Freezing.** A change to the references file or an image mid-run (including promoting a mockup or lowering an authority) stops the project for a human, who re-approves by resuming.

## Integration and retrospective

After all tasks pass, the developer assembles the project and a final verifier-first cycle checks every project AC and the integrated visual/audio result. Only this cycle's manifest/snapshot can become the delivered project.

Integration failures have an owner. A failing acceptance criterion is attributed to the tasks that produced it, and the repair goes to those tasks' specialists: artist for an art task, sound-designer for an audio task, fixer for a code task. Reviewer findings and verifier `repair_domains` keep their normal routing. The repair card carries `repair_attribution` (AC → task IDs). The developer only assembles; it never repairs. Integration does not reopen a completed task's cycle: repairs happen in the integration cycle, and a problem that needs new or different tasks goes back to the architect as a replan.

`factory-retro` runs after a successful or unsuccessful project outcome. It writes retained `RETRO.md` with evidence, root causes, prioritized improvements, tradeoffs and validation steps. It has a scratch workspace and cannot apply improvements, modify Factory configuration, change outcomes, or publish. A missing retro report cannot silently become success.

## Review panel for style-only tasks

The art-reviewer compares rendered output with the approved image. A task whose writer changed only files under `art/style/` (the style bible: `STYLE.md`, `style.json`, reference images) has nothing to render, so the panel leaves the art-reviewer out for that task (`work.style_only`); the other reviewers it needs still review it, and bible fidelity is still checked by the verifier's criteria and the deterministic contradiction scan. A task with real art, or a writer that reports no changed-file list, keeps the art-reviewer, and the final integration always gets the complete panel with in-engine screenshots.

## Scope-aware start check for repairs

A repair task must be able to start when the files it is assigned to repair already differ from the baseline manifest (an earlier attempt changed them without a new manifest). `fw.py check PROJECT_DIR --expect BASELINE --owned P1,P2` accepts a difference only for the listed files; every other difference, a missing or excluded file, a baseline sha12 mismatch, or an owned list that is empty, a pattern, unsafe or not in the manifest still fails (exit 4, or 2/3 for unusable ownership). The check stays mandatory and the baseline is never rewritten. The controller derives `OWNED_PATHS` from the explicit file paths of the findings routed to that repair (a finding without a usable path owns nothing, and the card then has no `--owned`), puts the exact command on the card, and requires the worker to copy fw's `start_check` object (baseline, owned, differed, accepted, rejected) into its metadata. On acceptance the controller verifies it (accepted files must be owned and differed, the baseline must be the card's, nothing rejected, and the task must be a repair that was given OWNED_PATHS) and records it as `start_check_owned` in the orchestration log and the `project_start_check_owned` event; anything else blocks.

## Fit modes for art assets

`scripts/sprite_fit.py` has two coverage modes and verifies its own result. `--coverage opaque` is for full-bleed art (walls, floors, backdrops, bands, tiles, anything its criterion requires to cover an area): it keeps every pixel and covers the target exactly, with no background removal and no transparent padding when the aspect ratios differ (a plain fit pads, which once left a floor band opaque only in its middle). `--coverage cutout` (the default) is for isolated sprites: the flat background becomes transparent and the content is centred on a transparent canvas. `--coverage auto --hint "<asset name and criterion>"` chooses from the requirement. A fit that would erase an opaque image exits 3 with a JSON diagnosis naming the transformation, whether it is a `tool_mode` or a `generation` defect, and the supported fix, so a wrong mode is never reported as a failed generation. The artist skill and every artist card state the rule; a repair that ends `BLOCKED` with `metadata.tool_defect` is refunded from the product repair budget (at most twice per task) and recorded as `tool_defect_refund`.

## Scope of the art review

For a task other than the final integration, the art-reviewer writes `render_check` findings, and may declare required tool incidents, only for the requirement ids in that task's `visual` list (the controller validates the findings against that list). Every approved requirement is still owned by some task, and the final integration reviews all of them with in-engine Game-view screenshots, so an environment-sprite review is no longer blocked for lacking an in-engine render of the characters or the HUD.

## Hermes patches and updates

The Factory depends on local patches to the Hermes source (`runtime/hermes-patches`: version-controlled git patches, a manifest, and `hermes_patches.py status|apply|export`). A Hermes update resets the source tree and removes them, so the plugin checks for them when it loads (`hermes_compat.py`) and withholds its run-board support claim if they are missing. The `factory_patch_check.py` cron job records `state/factory/hermes-patches.json`, alerts once per change, pauses new intake while patches are missing, and reapplies clean patches by default (`--check-only` disables that) (never during an update, never over a conflict, never restarting the gateway). See `runtime/hermes-patches/README.md`.

## Manifest include list

`PROJECT_DIR/.factory/include.txt` may mark a line `!path` (must exist now) or `?path` (a planned output of a later task). A missing path that no earlier manifest delivered is deferred and reported as `deferred_missing`, so an early task is not blocked by a later task's output; a path an earlier manifest delivered that has vanished, a `!` path, and excluded or unsafe paths still fail. The final integration card tells the writer to build the manifest with `fw.py manifest PROJECT_DIR --final`, where every listed path must exist.

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

- **Handoff-retry grant.** A stage that exhausted its handoff, scan or plan-correction retries stops for human review. `--decision-file` with `{"extra_handoff_retries": N}` (1 to 3, with a note, only when a budget is exhausted) gives those budgets N attempts back and resumes the same run: approvals, the approved plan and all other state are kept, and the grant is recorded in the orchestration log. It waives no gate. The retry message now states the exact summary header and artifact-path rules.
- **Waivers.** `resume_factory_workflow.py --decision-file` accepts `waivers` (one acceptance criterion, one path or narrow glob, optionally one reviewer, plus a reason). The finding keeps its original text in the gate record and on the waiver's audit trail; global waivers are rejected.
- **Structured constraints.** Plans may list top-level `constraints` and per-task `preserve`; a decision may add more. Kinds: `immutable` (paths), `palette` (`colors`), `layout`, `architecture`, `behavior` (`rules`) and `acceptance` (`acs`), each with an optional `paths` scope. Every task card carries them with their ids.
- **Specification conflicts.** A finding that can only be fixed by breaking a constraint is a specification conflict, not a defect. Mechanically: a finding on an immutable path. Reviewers and fixers report `spec_conflicts` (`constraint`, `reason`, `finding`). When relevant constraints exist, a read-only conflict check by a code reviewer runs before any repair is dispatched. A conflict stops the project for a human and spends no repair budget.
- **`extra_repairs`** (0 to 2, in a decision) grants that many additional repair cycles to the task in progress only.
- **Handoff recovery.** A malformed worker handoff retries only that stage, at most twice, with the exact reason, the required identity and the valid part of the previous result; retries exhausted escalates to human review. A missing or foreign run is never retried.
- **Repair budgets.** A repair that answers a genuine defect (a failed criterion or check, any finding) is a product repair and consumes the captured repair budget. A repair that answers only a verification-harness failure (`unverified:harness`) is an orchestration recovery with its own budget of 2; it can never exhaust the product budget. Every repair is recorded on the task as a charge (`work.charges`, event `project_repair_charged`); handoff retries, plan-validation retries and human resumes are logged under `orchestration_log` and charge nothing. An exhausted budget always stops the task for a human. A decision may grant `extra_repairs` (0 to 2, current task only) and `model_overrides` (up to 4 profiles, each `{provider, model, effort}`), which later stages of that profile use for this project; the catalog validates the model when it is used, the snapshot stays immutable, and the choice is recorded as `human_model_override`. `on_exhaustion` is accepted for old decision files and has no other effect.
- **Plan validation versus architectural replans.** A plan that fails structural validation (missing fields, tasks without numbered criteria, bad IDs, owners or dependencies, a cycle) goes back to the architect with every error and the required schema, at most twice, and spends no replan. Still invalid after that, the project stops for a human. The remaining architectural replans (a style bible that contradicts an approved reference, and the review stage when it is enabled) are bounded by `MAX_REPLANS`; a decision may grant `extra_replans` (one per decision) whose grant, reason and consumption are kept under `replan_grants`. A stage that finishes `BLOCKED` stops for a human, whatever `plan_defect` says.
- **Plan correction (separate from architectural replans).** Plan review classifies each finding (`finding_classes`) as a localized `correction` (wording, metadata, consistency) or `architectural`; unclassified means architectural, and a decision can classify the current findings by id (`plan_correction: ["F1"]`). If every blocking finding is a correction, the architect corrects the approved plan in place (at most 2 attempts per plan generation, accounted under `plan_corrections` and `orchestration_log`, never against the replan budget). The correction is checked mechanically: it must validate structurally, change no task, owner, dependency, need, risk or acceptance criterion (only `preserve` and constraints may differ), and keep every hash-like integrity baseline of the approved plan text (current values are reported beside them, never in place of them). A focused review then checks only the listed findings and the requirements they touch. A correction that fails twice stops for a human. A correction that changes architecture or acceptance criteria is not accepted as a correction: it becomes an ordinary architectural replan (full plan review, normal replan budget, logged as `plan_correction_escalated`), and only an exhausted replan budget stops for a human (grant `extra_replans` and resume with `--reevaluate`).
- **`retry_stage`** (decision key, or `resume_factory_workflow.py --retry-stage`, with a note) re-runs only the stage the project stopped on, including a `human_review` stop. A new `evidence_retry` row supersedes the stopped one; the earlier row, its result, every accepted stage, the approvals and the replan counts are kept. It is bounded to 2 per stage and cycle (`stage_retries`), refused while that stage is still running, logged as `human_stage_retry`, and cannot be combined with `--reevaluate`. Use it when the cause was tooling that has since been corrected; `--reevaluate` would reuse the stage's old `plan_defect` and stop again.
- **`--reevaluate`** re-judges existing stage evidence under the current rules without re-running stages, and also resumes a `human_review` stop.
- **Scoped secrets.** Workers never load a `.env`. A key a worker needs uses a dedicated, non-provider name (for the similarity gate, `FACTORY_SIMILARITY_API_KEY`) listed in that profile's `terminal.env_passthrough`; Hermes then supplies it from the profile's own `.env` to that profile's commands only (provider credential names such as `OPENROUTER_API_KEY` are refused by design). `scripts/factory_secrets.py doctor` checks this by name; `set` reads the value from a hidden prompt. Error text and artifacts redact the value.

## Verification

```sh
python -m unittest discover -s tests/workflow_v2 -p 'test_*.py' -v
python tests/workflow_v2/native_smoke.py
node --check runtime/factory-dashboard/factory_dashboard/assets/workflow_forms.js
```

The native smoke check needs the local Hermes source/environment. It creates a disposable board and uses synthetic handoffs; it does not call a model, run a paid task or enqueue anything on the production board.
