---
name: task-writing
description: How the architect (and directors) write the task graph in project-plan.json and PLAN.md so each task is small, owned, ordered and checkable. Load it before writing or revising a plan. The engine no longer rejects plans for style, so these rules are on you.
---

# Writing good tasks

The engine only checks that project-plan.json is well formed: valid ids, owners, dependencies, no cycles, asset producers before the code that integrates them. It does not check length, coverage or wording. A plan that follows the shape but is vague will pass and then fail in implementation, so write each task as if a stranger will build it with only your text.

## One task = one outcome
- One owner (developer, artist or sound-designer) and one observable result. If you wrote "and" between two outcomes, split it.
- Aim for work a single agent finishes in one cycle. Up to 40 tasks is fine; one 3-hour task is not.
- Titles are short (under 120 characters) and say the outcome, not the activity: "Player jumps 3 tiles with variable height", not "Work on movement".

## Acceptance criteria
- Each key is AC1, AC2, ... and each value is something a verifier can check by running, reading a file or looking at a render. Name the file, command, value or screen.
- Keep each criterion to a sentence or two. Put the long detail in PLAN.md under a heading and cite it ("see PLAN.md, Enemy AI").
- Never write a criterion that depends on a tool you have not confirmed exists. If a check needs a script or linter, check it can express your wording first (for example, its rule-id format). When unsure, describe the observable outcome and not the tool's output.
- Do not loosen a criterion just so work passes, and do not change director intent.

## Coverage
- Every project AC in PLAN.md should be stated by at least one task, using the same AC id. No reviewer checks the plan before tasks start, so this is on you. An AC no task states is recorded and becomes explicit work in the final integration task, which is late and costly: cover every AC yourself before you finish.

## Asset sizes and placement
- State an asset's world size and its placement or scale reference when the plan or the approved reference gives them (for example "drawn for 1.7 x 1.7 world units", "centre about 0.30, 0.49 of the frame", "figure 4.08 units"). That lets the artist derive a sensible size.
- Do not demand exact pixel dimensions unless the reference or a downstream requirement really needs them. An unspecified pixel size is an implementation decision for the artist, inside the asset class's range, not a gap for you to fill with an invented number and not a new mandatory field.

## Dependencies and ownership
- Asset tasks come first. A code task that uses an asset lists the artist or sound-designer task in dependencies.
- Declare only real dependencies. Needless chains stop tasks running in parallel.
- Set needs.art/audio/ui/ux only for domains the task really touches and the captured scope allows.
- Mark risk high only for security-sensitive, concurrency, data-migration or cross-cutting work.

## Manifest include list
- In PLAN.md's include list, mark each path a later task will create with `?` (for example `?Assets/Art/Room01/`) and any path that must already exist with `!`. Unmarked paths that do not exist yet are deferred until they are delivered; the final integration requires every listed path to exist.

## Approved references
- Every approved requirement id (V1, V2, ...) appears in the "visual" list of a task whose own acceptance text names that id. Never write a criterion that defers or weakens something an approved reference shows.

## Before you finish
1. Each task: one owner, one outcome, 1-3 sentences of acceptance, every criterion checkable.
2. Every PLAN.md AC appears in some task.
3. Dependencies match what each task reads or builds on.
4. On a revision, tasks listed in PROJECT_CONTEXT.completed_tasks are unchanged, and every file is rewritten in full.
