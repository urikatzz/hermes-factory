# Art verifier (level 1: asset checks)

## Intent and approved direction

Games built through Hermes need art that matches a defined look, and an independent check that it does. The existing `ui-reviewer` cannot render engine output (its SOUL reviews Unity statically and marks it `not_rendered`), and no stage describes how a game should look. The user approved building the verification side first, engine-agnostic, before any art-producing agents.

Level 1 checks assets themselves: sprites (PNG images, generated with Codex image generation), 3D models (exported from Tripo or from an agent driving Blender) and short game text. Level 2, in-game capture through a per-repo capture command, is a later step.

One shared engine serves two uses: a standalone command the user runs on a repo now, and a factory reviewer profile later. The approved approach is a Hermes `art-reviewer` profile whose deterministic scripts measure everything measurable, followed by a vision pass bounded by a written style bible.

This document does not authorize Git commits, pushes, dispatch-roster changes, workflow-template changes or paid model runs.

## Style bible (lives in each game repo)

```
art/style/
  STYLE.md       # written rules with IDs, applied by the vision pass
  style.json     # asset classes with measurable limits, applied by the linter
  palette.gpl    # optional GIMP palette
  reference/     # approved example images and renders
```

It lives outside `.factory/`, whose files other than PLAN.md and include.txt never enter manifests. The machine rules use JSON because the linter is standard-library only.

`STYLE.md` holds short rules, each headed by an ID: `S<n>` for visual rules and `T<n>` for text rules. A rule may be marked `(blocking)` after its ID; only such rules allow a vision finding above MEDIUM.

`style.json`:

```json
{
  "version": 1,
  "classes": [
    {"name": "character_sprite", "kind": "sprite",
     "match": ["Assets/Art/Characters/**/*.png"],
     "size": {"width": [32, 128], "height": [32, 128], "multiple_of": 16},
     "alpha": "required", "pixel_art": true,
     "palette": {"file": "palette.gpl", "tolerance": 4},
     "rules": ["S1", "S2", "S3"], "references": ["reference/hero_idle.png"]},
    {"name": "prop_model", "kind": "model",
     "match": ["Assets/Models/Props/**"],
     "triangles_max": 5000, "materials_max": 2, "texture_max_px": 1024,
     "height_m": [0.2, 2.0], "origin": "bottom_center", "rules": ["S2", "S4"]},
    {"name": "ui_copy", "kind": "text",
     "match": ["Assets/Text/ui/*.json"], "max_chars": 40,
     "forbidden": ["!!"], "rules": ["T1"]}
  ]
}
```

Kinds are `sprite`, `model` and `text`. All limits are optional per class. A class may override the default severity of any check with `"severity": {"<check>": "<SEV>"}`. Classes match by glob in order; when a file matches several classes the first wins and the overlap is recorded as a warning. Art files are files with extensions `.png .jpg .jpeg .webp .gif .psd .glb .gltf .fbx .obj .blend`, plus any file matched by a text class. `.blend` working files are reported as unclassified unless a class matches them; the exported model is what is reviewed.

Any rule ID referenced by a class must exist in STYLE.md, and every referenced file must exist. Otherwise the bible is invalid.

## Components

Source lives in this repo, following the `factory_ecc` pattern:

```
factory_art/
  style_bible.py        load/validate style.json + STYLE.md rule IDs; match files to classes
  png.py                standard-library PNG reader/writer (8-bit RGB, RGBA, indexed; others rejected)
  sprite_checks.py      size, alpha, palette distance, pixel-art edges/scaling; viewing variants
  model_checks.py       compare Blender stats JSON with class limits
  text_checks.py        length and forbidden patterns per string
  blender/render_model.py  runs inside `blender -b`: import, stats JSON, 4 views, contact sheet
  lint.py               CLI: art_lint <repo> [paths...] --out <dir> -> lint.json
scripts/art_check.sh    standalone: one art-reviewer run on a repo and optional paths
```

Installed later as `~/.hermes/factory-skills/worker/art-review/` (SKILL.md and scripts) and a new profile `~/.hermes/profiles/art-reviewer/` (SOUL.md; config copied from `ui-reviewer`, including the `vision` toolset and approvals floor).

No Pillow or pip installs: images use `png.py`; models use Blender's bundled Python. Blender is resolved from `$BLENDER`, then PATH, then `/Applications/Blender.app/Contents/MacOS/Blender`.

Text classes read JSON files whose string values (at any depth) are the strings checked; keys identify each string in findings. Other text formats are unsupported in this step.

## Review flow

1. Load the style bible. Invalid or missing: BLOCKER, no further checks.
2. Lint. Sprites are decoded and measured. Models are imported by Blender, which reports triangles, materials, texture sizes, bounding box and origin, and renders front, three-quarter, side and top views on a neutral background with fixed lighting, plus a contact sheet. Text strings are measured.
3. Vision pass (agent). For each sprite the agent opens a nearest-neighbour 4x upscale on transparent, mid-grey and dark backgrounds; for each model the contact sheet; alongside the class's reference images. It judges only against the class's rules.
4. Report: `report.md` and `lint.json`. Findings use `F<n>|SEV|<rule or check>|<file>|<problem>`. In factory mode the third field keeps the contract's meaning (an acceptance-criterion ID or `-`), so the line becomes `F<n>|SEV|<AC or ->|<file>|[<rule or check>] <problem>`. Verdict `NO_BLOCKING_FINDINGS` or `CHANGES_REQUIRED`; a BLOCKER or HIGH finding requires `CHANGES_REQUIRED`.

Lint results are facts the agent cannot overrule. The agent may only add vision findings, each citing a rule ID or reference image and the image path it judged; that image is attached. Observations that cite no rule are reported as NIT "style gap" suggestions for extending the bible.

Standalone runs copy the given paths (and `art/style/`) into the profile's workspace and never write to the repo. Factory runs follow the factory-worker contract: snapshot, manifest, delta. They review only manifest art files. A manifest without art files completes `NO_BLOCKING_FINDINGS` with metadata `art_surface: "none"`.

## Severities

| Check | Default |
|---|---|
| Bible missing/invalid, file unreadable, model import failure | BLOCKER |
| Over triangle, texture or material limit; size out of range or not a multiple; required alpha missing | HIGH |
| Text over `max_chars` | HIGH |
| Palette distance over tolerance; anti-aliased edges on pixel art; origin or height out of range | MEDIUM |
| Unclassified art file; text forbidden pattern | MEDIUM |
| Unsupported format (not checked) | LOW |
| Vision finding on a non-blocking rule | at most MEDIUM |
| Vision finding on a `(blocking)` rule | up to BLOCKER |

## Failures and limits

- Blender missing, crashing or over its timeout (default 120 seconds per model): those models' checks are `unverified:environment` in metadata and the report, with a `blocked_tools` entry. This is not counted against the asset; the review still completes.
- At most 40 images enter the vision pass per review. Further assets are listed in metadata `not_reviewed`, never silently skipped.
- Cycle 2+ (factory): review changed art files from `fw.py delta` first, then recheck every earlier finding's file.

## Validation

Python unittest, matching the existing packages:

- style_bible: valid/invalid JSON, unknown rule IDs, missing references, overlapping matches.
- png: round trips on generated RGB, RGBA and indexed fixtures; 16-bit and interlaced rejected; one real Codex-generated sprite.
- sprite_checks: intentional pass/fail fixture per rule.
- model_checks: stats JSON fixtures, no Blender needed.
- One Blender integration test with a generated cube and an oversized mesh as `.glb`; skipped with a clear message when Blender is absent.
- End-to-end: a `tests/art/fixtures/testgame/` repo with a bible and good/bad assets; `lint.py` must produce exactly the expected findings.
- One manual `art_check.sh` run with a real model on the fixture repo, recorded in a results document, to confirm vision findings cite rules. This is a paid run and requires the user's go-ahead.

## Rollout

1. Build and test in this repo. No Hermes changes.
2. Install the `art-review` skill and `art-reviewer` profile. Do not add it to any dispatch roster or workflow template.
3. The user runs it on real assets and tunes the bible.
4. Separate later step: reviewer capability in workflow templates and dispatch rosters.

## Out of scope

In-game capture (level 2), Art Director and Artist agents, Tripo or Codex generation, automatic asset fixes, audio, non-PNG image decoding.
