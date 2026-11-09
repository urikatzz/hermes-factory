---
name: software-factory
description: Coordinate the Hermes Kanban software factory for an issue or sprint task in a new or existing local project - architecture, implementation, independent verification plus a parallel review panel (Claude and Codex code review, security, UX and UI review), bounded fix cycles - ending in a verified LOCAL_DELIVERED result that lists the exact git/gh commands a human may run to publish. Also runs a non-production orchestration smoke test.
---

# Software factory (orchestrator lifecycle)

This skill is for factory-orchestrator only. Workers never load it; they get the `factory-worker` contract on every stage card. Use real Kanban workers, never simulated roles. You never write code, run commands or publish.

## Managed template roots
Roots with an associated workflow snapshot are executed by the deterministic Factory controller. Do not create stages, modify dependencies, complete or unblock these roots. Explain captured phases and recorded evidence to the user; changes to templates apply only to new tasks. Existing roots without a workflow snapshot continue using the legacy protocol below. Human review does not authorize waiving a required stage or extending a captured repair limit.

## Roster (exact assignee names; all are in the root kanban.dispatch_profiles)

| Role | Profile | Stages |
|---|---|---|
| foreman | factory-orchestrator | root card, intake, gates, outcome |
| architect | architect | PLAN (plan only) |
| writer | developer | IMPLEMENT, FIX, FIX PROBE |
| verifier | verifier | VERIFY, REVERIFY (execution evidence + release audit) |
| reviewer | claude-reviewer | CLAUDE REVIEW, CLAUDE RE-REVIEW |
| reviewer | codex-reviewer | CODEX REVIEW, CODEX RE-REVIEW (ONLY when the header says REVIEWERS: claude+codex; otherwise never create Codex cards) |
| reviewer | security-reviewer | SECURITY REVIEW, SECURITY RE-REVIEW (every job) |
| reviewer | ux-reviewer | UX REVIEW, UX RE-REVIEW (every job) |
| reviewer | ui-reviewer | UI REVIEW, UI RE-REVIEW (every job) |

Never assign to any other profile (fixer is retired; a card for an unlisted profile sits in `ready` forever). An implementer never verifies or reviews its own change. Missing credentials or an unavailable provider mean BLOCKED, never silent substitution.

## Intake (CHAT mode only)

0. Intake runs only in the factory-orchestrator profile (your SOUL says you are factory-orchestrator). In any other profile, tell the user to start `hermes -p factory-orchestrator` and stop.
1. Collect the request, the project folder (if any) and any acceptance criteria the user states. Ask at most one question, and only if the folder or mode is ambiguous.
2. DELIVERY is always `local`. If the user asks for GitHub, a PR or a push, say that the factory delivers locally and the root result will contain the exact git/gh commands for them to run.
3. PROJECT_MODE: `existing` when the user names a folder that already holds their project or asks to change/fix/extend it; otherwise `new`. `existing` always needs the absolute folder path. From chat there is one job per existing folder at a time; for several jobs at once, tell the user to file tickets with `python3 ~/.hermes/scripts/factory_ticket.py` (intake queue: Triage lane, `max_roots` open roots, one worktree per job on git repos).
4. PROJECT_DIR: the absolute path the user names, else `auto` (new mode only).
5. Prefer the queue: unless the request is a throwaway test, do NOT create a root. Create exactly ONE ticket in Triage instead: `kanban_create(title="TICKET: <short goal>", triage=true, body=<ticket>)` where the ticket is `FACTORY_TICKET v1`, `PROJECT: <repo alias the user named, e.g. bouncinggems, or an absolute path, or new; empty = default repo>`, `TYPE: feature|bug|chore|art|audio` (infer from the request; art = sprites, 3D models or a style bible; audio = sound effects, music cues, imported Suno music or a sound bible), `ACCEPTANCE: <criteria or none>`, `REQUEST:` and the request verbatim. The intake pump turns tickets into roots (worktree per job, concurrency cap) within a minute, and the publisher opens the draft PR when the job is delivered; tell the user the ticket id and that. A request like `bouncinggems: fix score overflow` names the repo before the colon. Only if the user explicitly wants a direct job, create the root below.
5b. Direct job: create exactly ONE root card: `kanban_create(title="FACTORY: <short goal>", assignee="factory-orchestrator", skills=["software-factory"], max_runtime_seconds=900, body=<root header + request>)`. No parents, no workspace args, no completion_contract (default local-only).
6. Tell the user the root id, how to watch it (`hermes kanban show <id>`, `hermes kanban runs <id>` or the board), that nobody is notified automatically (stalls and outcomes appear only on the board), and how to answer an escalation (`hermes kanban unblock <root id> --reason "waive F2 | retry | stop"`). Then stop. Never create stage cards from chat.

## Root header (first lines of the root body; the only source of truth for the job)

```
FACTORY_ROOT v2
DELIVERY: local
PROJECT_MODE: new | existing
PROJECT_DIR: auto | /abs/path
TYPE: feature | bug | chore | art | audio (optional; default feature)
REVIEWERS: claude | claude+codex  (optional; absent = claude+codex)
ISOLATION: dir | worktree        (optional; default dir)
REPO_DIR: /abs/repo               (worktree only)
BRANCH: factory/<ticket id>       (worktree only)
BASE_COMMIT: <sha12>              (worktree only)
MAIN_TREE_DIRTY: yes | no         (worktree only)
REPO / BASE_BRANCH / AUTO_PR / UNITY_CI   (registered repos only, written by the intake pump)
READ_FIRST: <files>              (registered repos: project guides every worker reads first, e.g. CLAUDE.md)
GATE: <path prefix> => <command>  (zero or more; the deterministic checks for changes under that prefix)
SLUG: <kebab-case, 2-5 words>
USER_ACCEPTANCE: <criteria the user stated, or none>
REQUEST:
<the request, quoted once, verbatim>
```

ISOLATION=worktree headers are written only by the intake pump (`~/.hermes/scripts/factory_intake.py`), which has already created the linked worktree at PROJECT_DIR on a fresh branch from BASE_COMMIT; to you PROJECT_DIR is an ordinary existing folder and every writer uses `workspace_kind="dir"` on it exactly as before. If MAIN_TREE_DIRTY is yes, uncommitted changes in the main checkout are NOT in the worktree: mention that in the PLAN card SCOPE. A root whose body has no valid header (for example one created with `hermes kanban create`) is DELIVERY=local, PROJECT_MODE=new, PROJECT_DIR=auto, SLUG from the title. Human comments on the root (for example `UNBLOCK: <note>`) are instructions only in "Resume after escalation".

## Outcomes

- LOCAL_DELIVERED (success): every gate passed on the final manifest. Complete the root (see "Final") with PROJECT_DIR, manifest sha12, snapshot path, AC results, waived items and the verifier's `publish_commands` copied verbatim.
- SMOKE_TEST_PASS: success outcome of the smoke test only.
- HUMAN_REVIEW_REQUIRED / BLOCKED / FAILED ("escalate"): first post `STATE ... decision=ESCALATE outcome=<OUTCOME> open=[...]`, then `kanban_block(kind=<K>, reason=<PLAIN>)` where PLAIN is written for a product owner who does not know this system: no card ids, no c1/c2 cycle codes, no manifest hashes, no jargon. Exactly this shape: line 1 `NEEDS YOUR DECISION: <one sentence: what you must decide>`; then `WHAT HAPPENED:` 2-3 plain sentences (what was built, what the checks and reviewers said, in words like "first build", "second fix round", "the independent check", "the Claude reviewer", "the security reviewer"); then `WHY IT STOPPED:` one sentence; then `OPTIONS:` 2-3 lettered choices, each one sentence with its consequence, and mark one `(recommended)`; then `REPLY WITH:` one `hermes kanban unblock <root id> --reason \"<ready-to-paste text for the recommended option>\"` line, and one more line per other option. Put technical detail (finding ids, card ids, digests) only in the STATE comment, never in PLAIN. K is `needs_input`, except in a run that started from "Resume after escalation": there use `capability` if the previous block was `needs_input` and vice versa (Hermes sends a second same-kind block after an unblock to triage, where `unblock` no longer works).
- Never create CREATE PR, PUBLISH, CI or FINAL VERIFY cards. Never commit, push, open a PR or merge; approvals.deny blocks those commands on every factory profile. Missing Git approval is never a reason to block.

## Stages (kanban_create arguments)

Every stage card: `title="<Stage as written in the table> (<root id>)"` (for example `CLAUDE RE-REVIEW c2 (t_ab12)`), `assignee` as below, `skills=["factory-worker"]`, `idempotency_key="<root>-<stage-key>"`, `max_runtime_seconds` as below, the body template below. Readers pass `workspace_kind="scratch"` explicitly; writers pass `workspace_kind="dir", workspace_path=PROJECT_DIR`.

| Stage | stage-key | Assignee | Workspace | Parents | max_runtime_seconds |
|---|---|---|---|---|---|
| PLAN | plan | architect | scratch | none | 1800 |
| IMPLEMENT | implement | developer | dir PROJECT_DIR | PLAN | 3600 |
| VERIFY c1 | verify-c1 | verifier | scratch | IMPLEMENT | 2400 |
| CLAUDE REVIEW c1 | claude-review-c1 | claude-reviewer | scratch | IMPLEMENT | 1800 |
| CODEX REVIEW c1 | codex-review-c1 | codex-reviewer | scratch | IMPLEMENT | 1800 |
| SECURITY REVIEW c1 | security-review-c1 | security-reviewer | scratch | IMPLEMENT | 1800 |
| UX REVIEW c1 | ux-review-c1 | ux-reviewer | scratch | IMPLEMENT | 2400 |
| UI REVIEW c1 | ui-review-c1 | ui-reviewer | scratch | IMPLEMENT | 2400 |
| FIX cN (N=2..4) | fix-cN | fixer | dir PROJECT_DIR | none | 3600 |
| REVERIFY cN | verify-cN | verifier | scratch | FIX cN | 2400 |
| CLAUDE RE-REVIEW cN | claude-review-cN | claude-reviewer | scratch | FIX cN | 1800 |
| CODEX RE-REVIEW cN | codex-review-cN | codex-reviewer | scratch | FIX cN | 1800 |
| SECURITY RE-REVIEW cN | security-review-cN | security-reviewer | scratch | FIX cN | 1800 |
| UX RE-REVIEW cN | ux-review-cN | ux-reviewer | scratch | FIX cN | 2400 |
| UI RE-REVIEW cN | ui-review-cN | ui-reviewer | scratch | FIX cN | 2400 |
| FIX PROBE (smoke only) | fix-probe | fixer | dir PROJECT_DIR | none | 600 |

Reviewers (the review panel): SECURITY, UX and UI reviews run on every job, in cycle 1 and on every FIX, whatever the header says; each specialist completes NO_BLOCKING_FINDINGS on its own when the change has no surface for it. The header field `REVIEWERS` only chooses the code reviewers: `claude` (the default for jobs from the intake queue) or `claude+codex` (also what a header without the field means). Below, every CODEX card exists only when REVIEWERS is claude+codex, and "every reviewer" / "the review panel" means every reviewer in use: the code reviewer(s) plus security, UX and UI. The dispatcher runs at most `max_in_progress` workers at once, so some readers of a cycle may wait in `ready`; that is normal.

Graph: PLAN -> IMPLEMENT -> (VERIFY || CLAUDE REVIEW || CODEX REVIEW || SECURITY REVIEW || UX REVIEW || UI REVIEW) -> GATE -> [FIX -> (REVERIFY || CLAUDE RE-REVIEW || CODEX RE-REVIEW || SECURITY RE-REVIEW || UX RE-REVIEW || UI RE-REVIEW) -> GATE] at most 3 times -> LOCAL_DELIVERED. If the gate after the third FIX still has blocking findings, the outcome is HUMAN_REVIEW_REQUIRED.

Pass exactly `skills=["factory-worker"]`, nothing else: the general-purpose skills in the worker profiles (test-driven-development, requesting-code-review, ...) tell the agent to ask the user, commit or auto-fix, which contradicts this contract. A card whose only skill is missing fails loudly at worker start; that is intended.

## Card bodies

Self-contained, target 2,000 characters (soft). The very first line of every stage card body is `WHAT: <plain-English label for the human reading the board>`, for example `WHAT: Fix round 2 of 3. Fix the problems the reviewers found: button overlaps the mascot.` or `WHAT: Independent check of the first build.` or `WHAT: Claude review of fix round 1.` or `WHAT: Security review of the first build.` (the board shows the start of the body under the title; "c3" means nothing to a human). Then the technical header below. No global rules (they live in factory-worker and the SOULs), no Git policy, never "read root". Workers must not need any other card except the ones named in INPUTS.

```
ROOT <id> | STAGE <name> | CYCLE <n> | PROJECT_MODE <new|existing>
PROJECT_DIR <abs path>   SLUG <slug>
MANIFEST <sha12, or "from <parent card id> handoff metadata.manifest_sha12">
BASELINE <sha12 or none>   BASELINE_TGZ <abs path or none>
INPUTS <abs paths / card ids to read>
GOAL <one or two sentences; the verbatim request goes only in the PLAN body>
ACCEPTANCE <AC ids, or "all ACs in .factory/PLAN.md">
SCOPE <see below>
DECISIONS <FIX and REVERIFY only: gate rulings they depend on, copied from STATE>
```

Stage-specific GOAL/SCOPE:
- PLAN: include REQUEST and USER_ACCEPTANCE verbatim. Ask for PLAN.md with numbered AC1..ACn and a "Manifest include list", attached via kanban_complete artifacts. SCOPE adds: "gate per GATES.md (new project: AC-GATE)", the header's READ_FIRST files, and by TYPE: bug = AC1 is a regression test that fails before the fix and passes after, plus root cause in the plan; feature = a short design (data, flow, touched modules) and ACs that describe observable behavior; any user-facing change also gets the user flow per AC and a viewport matrix (the UX and UI reviewers walk and shoot them); chore = no behavior change, ACs prove nothing regressed; art = the art-director plan (style task, or asset task with every asset's target path, class, limits and STYLE rule IDs, one AC per asset plus the art lint gate, and `style_sha256` from `art_lint.py --style-hash` for asset tasks); audio = the audio-director plan (`audio_task: style|sfx|music-cues|music-import`, one AC per asset or cue plus the audio lint gate where it applies, and `style_sha256` from `audio_lint.py --style-hash` for every task except style).
- IMPLEMENT: implement the plan; copy the PLAN.md attachment to PROJECT_DIR/.factory/PLAN.md; write .factory/include.txt from the plan; finish with `fw.py manifest`.
- VERIFY c1: full clean install, the gate command first (GATES.md; header GATE lines whose prefix matches a changed file are mandatory, run each), then every test/lint/typecheck/build/smoke script, the plan's probe/viewport matrix, screenshots inspected with vision, release audit, snapshot tarball attached, publish_commands. SCOPE: extra probes, if any.
- REVIEW c1 (every reviewer): targeted probes only (the verifier owns the full suite). SCOPE: focus areas, if any (for example the trust boundaries for SECURITY, the flows for UX, the screens and viewports for UI).
- FIX cN: SCOPE = one line per blocking item, `F<n>@<card>|SEV|AC|location|problem`; start from BASELINE.
- REVERIFY cN and every RE-REVIEW cN: SCOPE = exactly the FIX cN SCOPE lines (every reviewer re-checks the whole delta in its own discipline, not only its own findings). Re-reviews get no DECISIONS; list FIX cN's `rejected_findings` in the INPUTS of REVERIFY cN and every re-review, so they judge each rejection on evidence, not on the gate's ruling.
- INPUTS of FIX, REVERIFY and RE-REVIEW cards: the report.md and probe-script paths from each source card's `metadata.artifacts`, so reproducers survive into the next cycle.

## Root worker procedure (ROOT WORKER mode)

Your first message is `work kanban task <root id>`. Read your own card with `kanban_show()`; its comments hold your STATE lines. Keep the root incomplete until the final outcome. Pick exactly one branch:

### Waiting (a linked parent is not done yet)
If any card linked as a parent of the root is not done (for example a gate run crashed after creating a cycle), call `kanban_block(kind="dependency", reason="waiting for <stage ids>")` again and stop. Never re-run a gate on incomplete parents.

### First run (no STATE comment yet)
1. Parse the header. PROJECT_MODE=existing with PROJECT_DIR `auto` or missing: escalate BLOCKED ("existing mode needs the project folder"). Resolve PROJECT_DIR: `auto` -> `/Users/example/factory/<SLUG>-<root id>` (the root id makes it unique; never reuse an earlier root's path). A user-named path is used as given.
2. In this run, in order, create PLAN, IMPLEMENT (parents [PLAN id]), VERIFY c1, CLAUDE REVIEW c1, only if REVIEWERS is claude+codex CODEX REVIEW c1, then SECURITY REVIEW c1, UX REVIEW c1 and UI REVIEW c1 (all readers: parents [IMPLEMENT id]) per the table (the idempotency keys make a re-run of this step return the same cards). Record every returned id.
3. Post `STATE gate=0 fix_cycles=0 project_dir=<abs> mode=<new|existing> manifest=none decision=START cards=[...] next=[...]`.
4. `kanban_link(parent_id=<id>, child_id=<root>)` for VERIFY c1 and every review, then `kanban_block(kind="dependency", reason="waiting for cycle 1 VERIFY and reviews")`. That is the supported way for a running worker to gate its own card: the root parks in todo and resumes when those parents finish. Do not busy-poll, do not complete.

### Gate run (all linked parents are done, latest STATE decision is START or FIX; if it is PASS, go straight to Final, or to the smoke Final for a smoke root)
1. `kanban_show(task_id=<stage>)` for each reader of the current cycle and for the writer (IMPLEMENT or FIX cN). Use the latest completed run's summary and metadata. Do not read other cards.
2. Writer outcome: writer summary `VERDICT=BLOCKED` means escalate BLOCKED with its `blocked_reason` (the readers completed without reviewing). A writer handoff without `VERDICT=`, `contract: "factory-worker/v2"` or `manifest_sha12` means HUMAN_REVIEW_REQUIRED; never re-create a writer.
3. Reader validity: each reader summary starts with `VERDICT=`, and metadata carries `contract: "factory-worker/v2"` and `manifest_sha12`. An invalid reader is re-created once with idempotency key suffix `-r2` (same body, parents [writer]; link it, block again); a second invalid handoff from the same stage means HUMAN_REVIEW_REQUIRED.
4. Digest check: the writer's `manifest_sha12` must equal the verifier's and every reviewer's. Any mismatch means PROJECT_DIR changed outside the pipeline: HUMAN_REVIEW_REQUIRED.
5. Blocking items: every BLOCKER or HIGH finding line; every MEDIUM whose AC field names an AC; every AC the verifier marks `fail`, `unverified:code` or `unverified:harness`; verifier verdict FAIL; release audit FAIL; any `findings_truncated` > 0 (FIX SCOPE then adds "and the remaining findings in <report.md path>"). When sources disagree on severity, use the higher one unless a handoff records evidence for the lower. MEDIUMs with AC `-` go into FIX SCOPE whenever a FIX cycle is created anyway; otherwise they are waived with a one-line reason in STATE `waived=[...]` and in the final result. Never drop a MEDIUM silently. LOW/NIT are waived unless the request asked for them.
6. Human decisions (checked before steps 7 and 8): `blocked_tools` showing that a check an AC or security item depends on could not run, or any AC marked `unverified:environment` (needs a device, account, manual play or anything the headless verifier lacks), means HUMAN_REVIEW_REQUIRED with those items. Never a FIX item, never a reason to bypass a scanner. Exception when the header says UNITY_CI: yes: an AC marked `unverified:environment` only because it needs the Unity editor (client compile, EditMode/PlayMode tests, scene or prefab behavior) is NOT escalated; list it under `waived` as `pending repo CI (Unity)`, and the reviewers must still read the client code closely. Any other environment gap still escalates.
7. PASS (no blocking items): post STATE `decision=PASS`, then go to Final.
8. Blocking items and fix_cycles < 3: N = fix_cycles + 2. BASELINE = the current manifest sha12; BASELINE_TGZ = the `src-<sha12>.tgz` path in this cycle's VERIFY/REVERIFY `metadata.artifacts` (the stored attachment path; never build it by hand), or `none` if the verifier recorded `snapshot_attached: false` (readers then review the whole manifest). Create FIX cN, then REVERIFY cN and every RE-REVIEW cN of the review panel with parents [FIX cN], bodies per "Card bodies". Link all of these readers to the root, post STATE with `fix_cycles=<N-1>` and `decision=FIX`, then `kanban_block(kind="dependency", reason="waiting for cycle <N> REVERIFY and re-reviews")`.
9. Blocking items and fix_cycles == 3: escalate HUMAN_REVIEW_REQUIRED with the open items.
10. No-progress rule (checked before step 8): if a blocking item from the previous cycle reappears after FIX listed it in `rejected_findings` or recorded it as not fixable, or the verifier marks the failing check `preexisting`, or a finding carries `fix_available=false`, escalate HUMAN_REVIEW_REQUIRED at once with both sides' evidence. Never start another FIX for such an item.

### Resume after escalation (latest STATE decision is ESCALATE)
Human instructions are identified by content, not author: every comment newer than that STATE that does not start with `STATE ` is the human's instruction, whoever posted it (typically `UNBLOCK: <note>` from `hermes kanban unblock <id> --reason "<note>"`, or `HUMAN: <note>` relayed by the orchestrator chat). Your own comments always start with `STATE `. Follow the newest one:
- `waive <ids>` or `deliver`: allowed only if the digest check passed and the verifier's latest run has `publish_commands`. Go to Final with those items listed as waived by the human. Otherwise escalate again, saying why delivery is impossible.
- `retry` or `another cycle` (k = number of human resumes so far): if the open items include FIX-able findings, run gate step 8 for the next cycle (past 3 cycles only on this explicit instruction). If a writer or PLAN was BLOCKED, re-create that stage and every stage after it in the cycle with idempotency suffix `-h<k>` (same bodies, the human's note in DECISIONS). If the escalation was only a tool block or `unverified:environment`, re-create this cycle's readers with suffix `-h<k>`. Link the new readers, post STATE `decision=FIX`, block(dependency).
- `stop`: `kanban_complete(summary="OUTCOME=FAILED stopped by human: <note>", metadata={"outcome": "FAILED", ...})`.
- Anything else you can map onto one of these, do; otherwise, and when there is no new comment at all, escalate once more with the same outcome plus "awaiting human decision: waive <ids> | retry | stop", using the alternate block kind from "Outcomes" (never the same kind twice in a row, or the root lands in triage). Never re-run the gate unchanged.

### STATE comment (one per gate or resume, target 800 characters)
```
STATE gate=<n> fix_cycles=<n> project_dir=<abs> manifest=<sha12> decision=<START|FIX|PASS|ESCALATE> [outcome=<OUTCOME>]
cards=[all stage ids so far] blocking=[F<n>@<card>] waived=[F<n>@<card>: reason] open=[...] next=[card ids]
```
Right after every STATE comment, post ONE more root comment that starts `STATUS:` in plain English for the product owner, at most 4 short lines: where the job is (for example "Fix round 2 of 3 is running"), what just happened ("the UI reviewer asked for changes: the button overlaps the mascot"), what happens next, and whether you need anything from them. Use words, not codes: "first build", "fix round 2", "independent check", "Claude review", "Codex review", "security review", "UX review", "UI review". Never write card ids, c1/c2 codes or hashes in a STATUS comment.

Put detailed reasoning into the DECISIONS line of the affected FIX/REVERIFY cards, not into extra root comments. Never restate dispatch mechanics, Git policy or the request.

### Final (LOCAL_DELIVERED)
Check that every `publish_commands` line starts with `#`, `cd `, `sed `, `git ` or `gh `; otherwise escalate HUMAN_REVIEW_REQUIRED. Then call `kanban_complete` with:
- `summary`: `OUTCOME=LOCAL_DELIVERED MANIFEST=<sha12> PROJECT_DIR=<abs>` plus one sentence.
- `result`: PROJECT_DIR, manifest sha12, snapshot path, AC results (`AC1 pass ...`), waived items (with who waived them), then the heading `To publish (run yourself, optional):` followed by the latest verifier's `publish_commands`, one per line, verbatim.
- `metadata`: outcome, project_dir, manifest_sha12, snapshot, ac_results, waived, publish_commands, cards.
- `created_cards` only for ids created in this same run (normally none on the final run).

## Workspaces

- Writers (IMPLEMENT, FIX, FIX PROBE) use `workspace_kind="dir"`, `workspace_path=PROJECT_DIR`; the dispatcher creates the folder if missing and never deletes it. Dependency edges serialize writers; no reader ever runs while a writer runs. A writer retried by the dispatcher (timeout, crash, `failure_limit`) resumes from the current tree; that is why writers are never re-created with `-r2`.
- Readers (PLAN, VERIFY, REVERIFY, reviews) use scratch and work only on a manifest copy made by `fw.py snapshot`; they never write into PROJECT_DIR.
- The manifest is `PROJECT_DIR/.factory/SHA256SUMS`, built only from `.factory/include.txt` (explicit include list). `.env*`, `n8n/`, `node_modules/`, `dist/`, `.git/`, keys and archives are never in it and never copied. PROJECT_MODE=existing projects are allowed; only listed files are delivered, and the user's other folders (for example a live `n8n/` stack) are never touched.
- Immutable snapshots: VERIFY/REVERIFY attach `src-<sha12>.tgz` (unless it exceeds the 25 MB attachment cap); cycle-2+ reviewers diff it against the new manifest.
- Workers and you run no Git: no init, commits, branches or worktrees (approvals.deny stays in force on every profile), and factory cards never use `workspace_kind="worktree"` or projects. Isolation for parallel work on a git repo comes from the intake pump, which creates the job's linked worktree before the root exists (header ISOLATION: worktree); to the factory it is just a dir. Two roots on the same existing PROJECT_DIR with ISOLATION: dir are not serialized: never start a second one while the first is open. Roots with ISOLATION: worktree have their own PROJECT_DIR and may run side by side.

## Definition of done (LOCAL_DELIVERED)

- PLAN with AC1..ACn exists and is in the manifest as `.factory/PLAN.md`.
- The verifier demonstrated every AC on the final manifest (or the human waived it); release audit PASS; snapshot attached.
- Every reviewer in use (the code reviewer(s) per REVIEWERS plus security, UX and UI) completed in cycle 1 and on every FIX; zero unresolved BLOCKER/HIGH or AC-violating MEDIUM; every other MEDIUM fixed or listed as waived.
- All stage digests equal the final manifest sha12.
- The root result lists the publish commands; nothing was published.

## Non-production smoke test (board factory-smoke-test)

Use only when the root REQUEST starts with `SMOKE TEST`. Same card mechanics (bodies, skills, workspaces, links), bounded runtimes (children max_runtime_seconds 600), PROJECT_DIR auto (`/Users/example/factory/smoke-<root id>`), no external messages. Every smoke card body adds: "Smoke test: run no git or gh command of any kind and no package-manager command (there is no package.json)." Each worker reports its profile, task id and predecessor markers and completes with a unique marker `SMOKE:<root>:<stage-key>` using the stage-key column, lowercase (for example `SMOKE:t_ab12:implement`, `SMOKE:t_ab12:verify-c1`, `SMOKE:t_ab12:fix-probe`). Write the exact literal marker for each stage into the PLAN body and into that stage's own card body, so no worker has to derive it.

Graph: PLAN -> MOCK IMPLEMENT -> (VERIFY || CLAUDE REVIEW || CODEX REVIEW || SECURITY REVIEW || UX REVIEW || UI REVIEW) -> root GATE -> FIX PROBE -> root SMOKE_TEST_PASS.
- PLAN (architect): tiny PLAN.md with AC1 "hello.txt contains `SMOKE:<root>:implement`" (the literal marker, copied from the PLAN body) and a manifest include list `hello.txt`; attach it.
- MOCK IMPLEMENT (developer, dir, stage-key `implement`): write `hello.txt` with its marker, copy PLAN.md to `.factory/PLAN.md`, write `.factory/include.txt`, run `fw.py manifest`.
- VERIFY (verifier): `fw.py snapshot` with the expected sha12, check AC1 in the copy, `vision_analyze` `/Users/example/.hermes/hermes-agent/website/static/img/apple-touch-icon.png` and describe it in one sentence, `fw.py audit`, `fw.py publish-cmds`, attach the tarball; plus the write-guard probe below. No install/test/build steps; verdict PASS when AC1 holds and the audit is PASS.
- CLAUDE, CODEX, SECURITY, UX and UI REVIEW: `fw.py snapshot` with the expected sha12, read hello.txt, return NO_BLOCKING_FINDINGS with their marker; plus the write-guard probe.
- Write-guard probe (verifier and every reviewer): one `write_file` to `/tmp/factory-guard-probe-<task id>.txt` must return a write-guard block; record the block text in metadata `guard_probe`. If it succeeds, the smoke fails.
- GATE (checks only these items; the production gate rules do not apply): every stage so far has `contract: "factory-worker/v2"` in its metadata, every reader digest equals the MOCK IMPLEMENT sha12, every marker present, all guard probes blocked. Then create FIX PROBE (developer, dir PROJECT_DIR, no parents; body: run `fw.py check PROJECT_DIR --expect <sha12>`, change nothing, return the marker) and, in the same message right after kanban_create returns, post `STATE gate=1 fix_cycles=0 project_dir=<abs> manifest=<sha12> decision=PASS next=[<FIX PROBE id>]`, call `kanban_link(parent_id=<FIX PROBE>, child_id=<root>)` and `kanban_block(kind="dependency", reason="waiting for FIX PROBE")`: FIX PROBE is ready at once and must not finish before kanban_block. A smoke root whose latest STATE is PASS goes to the smoke Final (via Waiting while FIX PROBE is still open); never re-run the smoke GATE. If FIX PROBE finished before the block and the root was parked in needs_input, a plain `hermes kanban unblock <root>` resumes it into the smoke Final.
- Smoke Final: check FIX PROBE's marker and that its digest equals the MOCK IMPLEMENT sha12, then `kanban_complete` with summary `SMOKE_TEST_PASS` plus the marker chain and digest. Never LOCAL_DELIVERED for a smoke test. Any missing run, marker or digest means FAIL/BLOCKED with the exact missing evidence.

## Dispatch

The root gateway runs the Kanban dispatcher (every 10 s, at most 4 workers, 2-failure circuit breaker, allowlist = the roster above). Create real dependency-linked cards; the dispatcher starts ready workers automatically. Never ask the user to run dispatch commands. `kanban_create` has no max_retries parameter; the dispatcher's failure_limit applies. A card parked by the circuit breaker shows as blocked on the board and the root stays in todo until a human unblocks or archives it. If dispatch is unavailable, report the specific failure rather than pretending tasks ran.
