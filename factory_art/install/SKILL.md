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

## 2. Similarity gate

`SIMILARITY` means `python3 ${HERMES_SKILL_DIR}/scripts/art_similarity.py`. Run it as its own terminal command before you open any image yourself:

`SIMILARITY <workspace>/lint/lint.json --out <workspace>/similarity.json`

It sends each rendered asset and its reference images to the Jev model on OpenRouter (`OPENROUTER_API_KEY`) and prints a one-line JSON summary. `similarity.json` holds a 0-100 `score`, a `status` and the largest `differences` per asset. The scores are measured facts for this review: never raise, drop or dispute them.

- `gate: "pass"`: every asset scored at least 80. Continue with section 3 to find what is still missing.
- `gate: "fail"`: do not run section 3. For each asset with `status: "fail"` report a HIGH finding `[similarity] <score>% match, below 80%: <differences>`. For each `status: "no_reference"` report a BLOCKER finding `[similarity] no reference image for this asset class`, and in factory mode set metadata `plan_defect` to say which class lacks a reference. Verdict `CHANGES_REQUIRED`.
- `gate: "blocked"`: the model or its key is unavailable. Report `blocked_tools: ["jev-similarity"]`; do not approve and do not substitute your own estimate.

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

1. `fw.py snapshot` and work only in the printed `src_dir`.
2. From cycle 2: run `fw.py delta`, then pass each changed art file as `--first`, and re-check every file named in SCOPE findings.
3. `LINT <src_dir> --out "$HERMES_KANBAN_WORKSPACE/lint"`. If `art_files` is 0, complete `NO_BLOCKING_FINDINGS` with metadata `art_surface: "none"` and one sentence why.
4. A `bible` BLOCKER on a factory task usually means `art/style` is missing from `.factory/include.txt`. Say so in the finding.
5. Metadata finding lines keep the contract's AC field: `F<n>|SEV|<AC id or ->|<file>|[<rule or check>] <problem>`. Map each finding to the AC it threatens in `.factory/PLAN.md`.
6. Extra metadata: `art_surface: "assets"`, `images_inspected` (count), `not_reviewed`, `unverified`, and the lint `blocked_tools`.
7. After lint, run the similarity gate into `"$HERMES_KANBAN_WORKSPACE/similarity.json"` and follow section 2. On final integration (in-engine screenshots) the gate does not apply.
8. Attach `report.md`, `lint/lint.json`, `similarity.json` and every image you cite. Then `fw.py clean` and `kanban_complete`.
