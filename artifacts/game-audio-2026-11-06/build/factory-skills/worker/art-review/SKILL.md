---
name: art-review
description: Procedure and scripts for the art-reviewer - lint sprites, 3D models and game text against a repo's art/style bible, then judge the prepared images against its numbered rules.
---

# Art review

`LINT` means `python3 /Users/example/.hermes/factory-skills/worker/art-review/scripts/art_lint.py` (standalone queries give the exact command). Run it as its own terminal command, never through `bash -c` or a pipe.

## 1. Lint

`LINT <src_dir> --out <workspace>/lint [--first <changed file>]...`

It prints a one-line JSON summary. Full results are in `<workspace>/lint/lint.json`:

- `art_files`: 0 means there is nothing to review.
- `findings` and `lines`: lint findings. They are measured facts. Never drop, downgrade or dispute them.
- `assets[]`: `file`, `class`, `kind`, `rules` (STYLE.md IDs), `references` (absolute image paths), `images` (absolute paths prepared for you), `vision` (false means over the image budget).
- `not_reviewed`, `unverified` (Blender unavailable: environment, not the asset's fault), `blocked_tools`, `warnings`.

## 2. Judge

Read `<src_dir>/art/style/STYLE.md`. For each asset with `vision: true`:

- Sprite: open all three `images` (transparent, grey and dark backgrounds, nearest-neighbour upscaled) and each `references` image with `vision_analyze`.
- Model: open its contact sheet (front, three-quarter, side and top views) and the references.
- Text: read the file in `<src_dir>` and judge every string against the class's T rules.

Judge only against that asset's `rules`. Text findings use `<file>#<key path>` as the location (for example `Assets/Text/menu.json#menu.title`). Each vision finding names the rule ID (or reference image) it breaks and the image path you judged. A vision finding is at most MEDIUM unless STYLE.md marks the cited rule `(blocking)`. Something that bothers you but breaks no listed rule is a NIT `style gap: <suggested rule>`. Never judge an image you did not open.

## 3. Report

Write `report.md`:
1. Summary and verdict.
2. Lint findings, in lint.json order.
3. Vision findings: severity, rule, file, image path, problem, recommended fix.
4. Not reviewed, unverified and blocked tools.
5. Bible warnings and style-gap suggestions.

Number the findings F1... with lint findings first, then vision findings. Verdict: `CHANGES_REQUIRED` if any BLOCKER or HIGH finding exists (lint or vision); otherwise `NO_BLOCKING_FINDINGS`.

## Standalone mode (query starts with MODE=standalone)

The query gives `SRC_DIR`, `OUT_DIR` and `LINT`. Run `LINT SRC_DIR --out OUT_DIR/lint`, judge, and write `OUT_DIR/report.md`. Finding lines use `F<n>|SEV|<rule or check>|<file>|<problem>`. Write nothing outside `OUT_DIR`. End your reply with `VERDICT=<verdict> REPORT=OUT_DIR/report.md`.

## Factory mode (card with a STAGE header)

Follow the factory-worker contract preloaded on the card.

1. `fw.py snapshot` and work only in the printed `src_dir`.
2. From cycle 2: run `fw.py delta`, then pass each changed art file as `--first`, and re-check every file named in SCOPE findings.
3. `LINT <src_dir> --out "$HERMES_KANBAN_WORKSPACE/lint"`. If `art_files` is 0, complete `NO_BLOCKING_FINDINGS` with metadata `art_surface: "none"` and one sentence why.
4. A `bible` BLOCKER on a factory task usually means `art/style` is missing from `.factory/include.txt`. Say so in the finding.
5. Metadata finding lines keep the contract's AC field: `F<n>|SEV|<AC id or ->|<file>|[<rule or check>] <problem>`. Map each finding to the AC it threatens in `.factory/PLAN.md`.
6. Extra metadata: `art_surface: "assets"`, `images_inspected` (count), `not_reviewed`, `unverified`, and the lint `blocked_tools`.
7. Attach `report.md`, `lint/lint.json` and every image you cite. Then `fw.py clean` and `kanban_complete`.
