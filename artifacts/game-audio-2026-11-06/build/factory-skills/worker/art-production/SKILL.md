---
name: art-production
description: Procedure and scripts for the Factory artist - Codex concept images, sprite fitting, Tripo image-to-3D with a Blender blockout fallback, Blender cleanup, and the art lint gate.
---

# Art production

Tools (run each as its own terminal command, never through `bash -c` or a pipe):

- `IMAGE` = `sh /Users/example/.hermes/factory-skills/worker/art-production/scripts/codex_image.sh <prompt-file> <out.png>`: one Codex image (up to 5 minutes). Exit 0 means `out.png` exists and decodes.
- `FIT` = `python3 /Users/example/.hermes/factory-skills/worker/art-production/scripts/sprite_fit.py <in.png> <out.png> --size WxH [--palette <art/style/palette file>]`: flat background to alpha, nearest-neighbour fit to the class size, palette quantize.
- `TRIPO` = `python3 /Users/example/.hermes/factory-skills/worker/art-production/scripts/tripo_model.py <concept.png> <out.glb>`: Tripo image-to-model, up to 10 minutes. Exit 0 done, 3 fallback (no key, no credits, API down; nothing was charged), 1 failed (any failure once the create request was sent, including a lost reply: possibly charged). It prints JSON with `tripo_tasks`; copy those IDs into your metadata every time, including failures. `unknown-create` in `tripo_tasks` means a task may have been created and charged without an ID coming back.
- `BLENDER` = `sh /Users/example/.hermes/factory-skills/worker/art-production/scripts/blender_run.sh`:
  - `cleanup <in.glb> <out.glb> --height <m> --origin bottom_center|center`
  - `blockout <concept.png> <out.glb> --height <m> --spec <parts.json> [--palette <file.gpl>] [--origin ...]`
- `LINT` = `python3 /Users/example/.hermes/factory-skills/worker/art-review/scripts/art_lint.py <PROJECT_DIR> <changed art paths> --out <PROJECT_DIR>/.factory/tmp/art-lint --fail-on-blocking`: exit 1 means a BLOCKER or HIGH finding; read `lint.json` there.

Scratch files (prompt files, raw generations, blockout specs, lint output) go under `PROJECT_DIR/.factory/tmp/`. Deliverables go only to the target paths in PLAN.md and, for models, `art/concepts/<name>.png`.

## Before you start

Read `.factory/PLAN.md`, then `art/style/STYLE.md` and `art/style/style.json`. For every asset note its class, size or triangle/height limits, palette file and STYLE rule IDs. Look at the class reference images with `vision_analyze`.

## Prompts

Write one prompt file per asset in the imagegen schema: `Use case:` (stylized-concept for models, illustration-story or stylized-concept for sprites), `Asset type:` (game sprite or 3D model concept), `Primary request:` (the plan's concept prompt), `Style/medium:` and `Color palette:` (from STYLE.md and the palette file), `Composition/framing:`, `Constraints:` and `Avoid:`. Sprites: one centred subject on a flat plain background, no shadow, no text, no frame. Model concepts: one object, neutral three-quarter view, plain light background, even lighting, no text.

## Sprite

1. `IMAGE` to `.factory/tmp/raw/<name>.png`.
2. `FIT` to the target path with the class size and, when the class has one, its palette file.
3. Look at the result with `vision_analyze`, then `LINT` the file.
4. If lint has a BLOCKER or HIGH finding for it, or it plainly breaks a cited STYLE rule, rewrite the prompt once (one targeted change) and repeat steps 1-3 once. Then stop and report what is left.

Record `{"path": <target>, "kind": "sprite", "route": "codex", "concept": ".factory/tmp/raw/<name>.png"}`.

## Model

1. `IMAGE` to `art/concepts/<name>.png` (part of the deliverable).
2. `TRIPO` to `.factory/tmp/raw/<name>.glb`.
   - Exit 0: `BLENDER cleanup` it to the target path with the class height (use the middle of `height_m`) and origin.
   - Exit 3: fallback. Look at the concept with `vision_analyze`, write `.factory/tmp/<name>.parts.json` (at most 64 cube/cylinder/sphere/cone parts, metres, Z up, ground at z=0, colours sampled from the concept with `"sample": [u, v]` or palette hex), then `BLENDER blockout` to the target path with `--height` and, when the class has one, `--palette`. Record the fallback reason from TRIPO's JSON.
   - Exit 1: do not call TRIPO again for this asset (a charged or possibly charged task is never retried). Use the blockout route and record the error.
3. `LINT` the model. Fix only what the finding names (height, origin, triangles, materials) with one more `cleanup` or `blockout` run.

Record `{"path": <target>, "kind": "model", "route": "tripo" or "blockout", "concept": "art/concepts/<name>.png"}`.

## Style task

Only when the plan is a style task: write `art/style/STYLE.md`, `art/style/style.json`, the palette file and the reference images exactly as the plan specifies (references with `IMAGE`, then `FIT` when the plan gives a size). Then run `python3 /Users/example/.hermes/factory-skills/worker/art-review/scripts/art_lint.py <PROJECT_DIR> --check-bible` and fix until it prints `"bible": "ok"`.

## Completion

- Run `LINT` on every changed art path. Record it in `checks_run`, and in `failed_checks` when it exits 1.
- Metadata adds `assets` (the records above), `fallbacks` (one short reason per fallback asset), `tripo_tasks` (every Tripo task ID from every TRIPO run).
- Add every target path and every `art/concepts/<name>.png` to `.factory/include.txt`; never add `.factory/tmp/`.

## Repair

Regenerate or refit only the assets named in SCOPE findings, by the same route, except: once an asset has a recorded Tripo task ID or `unknown-create` in `tripo_tasks` (from any run in this job), never call TRIPO for it again, whatever the finding; fix it with `BLENDER cleanup` on the existing GLB or with the blockout route.

## Rules

- An asset task never writes `art/style/`. Only a style task does.
- Never edit lint or bible files to make lint pass. Never fake a route: `route` says how the file was really made.
- `TRIPO_API_KEY` reaches the script through the environment. Never print, read or copy `.env` files or the key.
