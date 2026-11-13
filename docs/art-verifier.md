# Art verifier

Checks a game's sprites (PNG), 3D models (glb/gltf/fbx/obj, rendered with Blender) and JSON game text against the game repo's own style bible in `art/style/`. Level 1 only: assets are checked on their own, not inside the engine.

## Style bible

`art/style/STYLE.md` holds numbered rules (`**S1** ...` for visuals, `**T1** ...` for text). Add `(blocking)` after an ID to let vision findings on that rule block. `art/style/style.json` holds asset classes; see `docs/superpowers/specs/2026-10-21-art-verifier-design.md` for every field. Optional `palette.gpl` and `reference/` images live alongside.

## Lint only (no model, free)

    python3 scripts/art_lint.py <game-repo> [paths...] --out /tmp/art-lint

Review images and `lint.json` land in the output directory. A sample repo with good and bad assets: `python3 tests/art/art_fixtures.py /tmp/art-testgame`.

## Full review (lint + vision, one paid run)

    ~/.hermes/factory-skills/worker/art-review/scripts/art_check.sh <game-repo> [paths...]

Copies the bible and the given paths to a private temporary directory, runs the `art-reviewer` profile once and prints `REPORT=<path>`. The game repo is never written. Paths that leave the repo, including through symlinks, are refused.

## Install

    sh scripts/install_art_review.sh
    hermes profile create art-reviewer --clone-from ui-reviewer --no-alias \
      --description "Independent art reviewer: checks sprites, 3D models and game text against the repo style bible."
    cp ~/.hermes/factory-skills/worker/art-review/SOUL.md ~/.hermes/profiles/art-reviewer/SOUL.md

These standalone installation commands do not add dispatch or workflow configuration. In an installed [project workflow v2](project-workflows.md), the controller selects `art-reviewer` for art tasks after verification passes, and for final integration. Those stages additionally require retained comparisons against the art director's plan, including actual in-engine images for final integration.

## Known limits

- PNG only for sprites; other image formats are reported as unsupported (LOW).
- If the bible is broken and the repo contains only JSON text assets, nothing is flagged.
- Blender missing, crashing or timing out (120 s per model) marks those models `unverified:environment`, not failed.
- At most 40 images (views plus references) go to the vision pass; the rest are listed in `not_reviewed`.

## Validation

    python3 -m unittest discover -s tests/art -p 'test_*.py' -v
