---
name: art-review
description: Procedure and scripts for the art-reviewer - lint sprites, 3D models and game text against a repo's art/style bible, then judge the prepared images against its numbered rules.
---

# Art review

`LINT` means `python3 ${HERMES_SKILL_DIR}/scripts/art_lint.py` (standalone queries give the exact command). Run it as its own terminal command, never through `bash -c` or a pipe.

## 1. Lint

`LINT <src_dir> --out <workspace>/lint [--first <changed file>]...`

It prints a one-line JSON summary. Full results are in `<workspace>/lint/lint.json`:

- `art_files`: 0 means there is nothing to review.
- `findings` and `lines`: lint findings. They are measured facts. Never drop, downgrade or dispute them.
- `assets[]`: `file`, `class`, `kind`, `rules` (STYLE.md IDs), `references` (absolute image paths), `images` (absolute paths prepared for you), `vision` (false means over the image budget).
- `not_reviewed`, `unverified` (Blender unavailable: environment, not the asset's fault), `blocked_tools`, `warnings`.

## 2. Similarity gates

**Never score an isolated sprite against an approved reference scene.** A human-approved reference is one composed frame; a single sprite scored against it can only fail for "having no characters". When the card lists `approved_references`, skip the per-asset gate below completely and judge each requirement your task owns with vision against the ORIGINAL reference (section 3). The only similarity score against an approved reference is the full-scene score (2b).

### 2a. Per-asset gate (only when the card has NO approved_references: assets against their own style-bible reference images)

`SIMILARITY` means `python3 ${HERMES_SKILL_DIR}/scripts/art_similarity.py`. Run it as its own terminal command before you open any image yourself:

`SIMILARITY <workspace>/lint/lint.json --out <workspace>/similarity.json`

It sends each rendered asset and its reference images to the Jev model on OpenRouter (credential `FACTORY_SIMILARITY_API_KEY`, falling back to `OPENROUTER_API_KEY`; the profile forwards only the first through `terminal.env_passthrough`, since Hermes never forwards provider credential names) and prints a one-line JSON summary. `similarity.json` holds a 0-100 `score`, a `status` and the largest `differences` per asset. The scores are measured facts for this review: never raise, drop or dispute them.

- `gate: "pass"`: every asset scored at least 80. Continue with section 3 to find what is still missing.
- `gate: "fail"`: do not run section 3. For each asset with `status: "fail"` report a HIGH finding `[similarity] <score>% match, below 80%: <differences>`. For each `status: "no_reference"` report a BLOCKER finding `[similarity] no reference image for this asset class`, and in factory mode set metadata `plan_defect` to say which class lacks a reference. Verdict `CHANGES_REQUIRED`.
- `gate: "blocked"`: the model or its key is unavailable. Never load a `.env` or look for the key yourself. Record it as an unresolved required tool incident (`blocked_tools: ["jev-similarity"]` and `tool_incidents`) and say the human should run `factory_secrets.py doctor`; do not approve and do not substitute your own estimate.

### 2b. Full-scene gate (final integration with approved references; mandatory, pass is 80/100)

`SCENE_SCORE` means `python3 ${HERMES_SKILL_DIR}/scripts/scene_score.py`. It scores the COMPLETE assembled scene, captured from the game engine, against the COMPLETE original approved reference.

1. Capture the scene yourself, never trusting the writer's capture: `fw.py check PROJECT_DIR --expect <this review's manifest>`, then `python3 $HOME/.hermes/factory-skills/worker/unity-scene/scripts/unity_scene_capture.py --project PROJECT_DIR --layout art/scene/scene-layout.json --out <workspace>/scene --required <the approved requirement ids on the card>`. It builds a real scene from the layout in an isolated clone, renders it with the game engine and writes `scene.png` and `scene-render.json` (the engine's own attestation and the scene's completeness). It must be a real engine render: never an image you generated or painted, never the reference, never one asset. If the layout is missing or the capture exits 3, no scene exists: report CHANGES_REQUIRED with a HIGH finding on the integration (`no scene layout`, or the capture's stage and message) and score nothing else. A scene that still misses required reference elements (`completeness.missing`) is a preliminary composition: it is scored but can never be accepted, so report CHANGES_REQUIRED naming the missing elements.
2. `SCENE_SCORE --reference <the ORIGINAL approved reference in PROJECT_DIR> --screenshot <workspace>/scene/scene.png --render-record <workspace>/scene/scene-render.json --out scene-similarity.json --assets <the scene's asset files, comma separated>`. With no API key forwarded it scores through the machine's Codex login; an unattested render is refused.
3. Exit 0 (`status: pass`, score >= 80): continue with section 3. Exit 2 (`status: fail`): report one HIGH finding per ranked difference, `[scene] <impact>/5 <aspect>: <description> | responsible: <asset or scene settings> | repair: <instruction>`, with the responsible asset file as the finding's file, verdict `CHANGES_REQUIRED`. Add your own diagnosis of why the whole scene falls short (colour, lighting, texture, proportion, missing detail, composition), rank what matters most, and name the assets that already match and must be preserved. Repair the cause, never the score.
4. Exit 3 (`status: blocked`): no admissible engine render, wrong framing, a copy of the reference, or no credential. No score exists. Record an unresolved required tool incident (`blocked_tools: ["scene-similarity"]`); never estimate or invent a score and never substitute a per-asset score.
5. When the card shows a SCENE SCORE HISTORY, compare with it: say whether the score improved, why, and whether the last repair addressed the ranked differences.

Retain `scene-similarity.json`, `scene-render.json`, the screenshot and `scene-compared.png` as completion artifacts.

## 3. Judge

Read `<src_dir>/art/style/STYLE.md`. For each asset with `vision: true`:

- Sprite: open all three `images` (transparent, grey and dark backgrounds, nearest-neighbour upscaled) and each `references` image with `vision_analyze`.
- Model: open its contact sheet (front, three-quarter, side and top views) and the references.
- Text: read the file in `<src_dir>` and judge every string against the class's T rules.

Judge only against that asset's `rules`. Text findings use `<file>#<key path>` as the location (for example `Assets/Text/menu.json#menu.title`). Each vision finding names the rule ID (or reference image) it breaks and the image path you judged. A vision finding is at most MEDIUM unless STYLE.md marks the cited rule `(blocking)`. Something that bothers you but breaks no listed rule is a NIT `style gap: <suggested rule>`. Never judge an image you did not open.

## 4. Report

Write `report.md`:
1. Summary and verdict, including the similarity gate result and each asset's score.
2. Lint findings, in lint.json order.
3. Similarity findings, then vision findings: severity, rule, file, image path, problem, recommended fix.
4. Not reviewed, unverified and blocked tools.
5. Bible warnings and style-gap suggestions.

Number the findings F1... with lint findings first, then similarity findings, then vision findings. Verdict: `CHANGES_REQUIRED` if any BLOCKER or HIGH finding exists (lint or vision); otherwise `NO_BLOCKING_FINDINGS`.

## Standalone mode (query starts with MODE=standalone)

The query gives `SRC_DIR`, `OUT_DIR` and `LINT`. Run `LINT SRC_DIR --out OUT_DIR/lint`, then `SIMILARITY OUT_DIR/lint/lint.json --out OUT_DIR/similarity.json`, judge only if the gate passed, and write `OUT_DIR/report.md`. Finding lines use `F<n>|SEV|<rule or check>|<file>|<problem>`. Write nothing outside `OUT_DIR`. End your reply with `VERDICT=<verdict> REPORT=OUT_DIR/report.md`.

## Factory mode (card with a STAGE header)

Follow the factory-worker contract preloaded on the card.

**You are the single final visual gate.** The factory runs you exactly once per delivery, at final integration, on the complete game: every required feature, asset, HUD, enemy, animation, effect and scene element is already built and integrated. You are never run on an individual asset or task, and no task waits for or is blocked by you. Judge the real engine render of the whole scene (section 2b), then the approved requirements. If a required element is missing the scene is a preliminary composition and cannot be accepted: report CHANGES_REQUIRED naming what is missing, and the factory repairs (or plans the missing task) and runs you again.

1. `fw.py snapshot` and work only in the printed `src_dir`.
2. From cycle 2: run `fw.py delta`, then pass each changed art file as `--first`, and re-check every file named in SCOPE findings.
3. `LINT <src_dir> --out "$HERMES_KANBAN_WORKSPACE/lint"`. If `art_files` is 0, complete `NO_BLOCKING_FINDINGS` with metadata `art_surface: "none"` and one sentence why.
4. A `bible` BLOCKER on a factory task usually means `art/style` is missing from `.factory/include.txt`. Say so in the finding.
5. Metadata finding lines keep the contract's AC field: `F<n>|SEV|<AC id or ->|<file>|[<rule or check>] <problem>`. Map each finding to the AC it threatens in `.factory/PLAN.md`.
6. Extra metadata: `art_surface: "assets"`, `images_inspected` (count), `not_reviewed`, `unverified`, and the lint `blocked_tools`.
7. At final integration with approved_references: run the full-scene gate (2b) into `"$HERMES_KANBAN_WORKSPACE/scene-similarity.json"`; there is no per-asset similarity gate in factory mode. With no approved_references on the card, review as the card says; never score an isolated sprite against a reference scene.
8. Attach `report.md`, `lint/lint.json`, `similarity.json` when you ran it, the scene files from 2b when you ran them, and every image you cite. Then `fw.py clean` and `kanban_complete`.
