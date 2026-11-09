# Game art in the Factory (Art type, Art Director, Artist)

## Intent and approved direction

The level-1 art verifier exists (`docs/superpowers/specs/2026-10-21-art-verifier-design.md`) and is installed as the `art-reviewer` profile, which the Factory cannot yet schedule. This step makes art a Factory product:

- Step 2: `art-reviewer` is selectable in any workflow template, and the asset linter runs in verification.
- Step 3: an Art Director plans art, and an Artist produces it.

The user approved:

- A new task type **Art** with a default **Game Art** template.
- Production chain: **Codex concept image → Tripo image-to-3D → Blender cleanup**. Sprites are Codex images. Without a Tripo key or credits, the Artist builds a simple Blender model from the concept image and records the fallback.
- A missing style bible is created by its own Art task. The user approves it by accepting that delivery. Asset tasks on a repo without a bible stop at preparation.

This document does not authorize Git commits, pushes or paid Tripo usage beyond the user's own key.

## Constraints from the installed Factory

- **Source and bundle:** the live code is `~/.hermes/factory-dashboard/factory_dashboard/` (dashboard). It is bundled into `~/.hermes/plugins/factory-models/factory_dashboard/` (gateway hooks) by `scripts/bundle_factory_plugin.py`.
- **No tests:** neither copy has tests in this install.
- **Profile map:** profiles and capabilities are enumerated in `workflow_types.py:5-11`.
- **Task types:** listed in `workflow_types.py:12`, `task_submission.py:21`, `scripts/factory_ticket.py:12`, `scripts/factory_lib.py:156`, `scripts/factory_intake.py:91`, `scripts/factory_publish.py:172`, `assets/workflow_forms.js:38` and `assets/task_forms.js:43`.
- **Reviewer rule:** every template needs `claude-reviewer` or `codex-reviewer` (`workflow_types.py:59`).
- **Verify stage:** exactly one verify stage is required. Only `verifier` has that capability.
- **New roles:** each needs:
  - a `model-catalog.json` entry;
  - a `factory_defaults.roles` row in `state/factory/task-settings.db`, added by a one-off migration that bumps `revision`, because `save_default` rejects unknown roles;
  - an entry in the root `kanban.dispatch_profiles`.
- **Planning is read-only:** preparation produces `PLAN.md`, acceptance IDs and the include list only.
- **No pause and resume:** a stopped (`human_review`) task is replaced by a new task.
- **Profile models:** Claude (`anthropic`), Codex (`openai-codex`) or OpenRouter only. Copilot is not licensed.

## Profiles

| Profile | Capabilities | Model | Toolsets | Skills |
|---|---|---|---|---|
| `art-director` | prepare | anthropic / claude-opus-5-5 | kanban, file, terminal, vision | factory-worker, art-review (to read bible rules) |
| `artist` | implement, repair | openai-codex / gpt-6-luna (developer's model) | kanban, file, terminal, vision | factory-worker, art-production |
| `art-reviewer` | review | anthropic / claude-sonnet-5-5 | unchanged | factory-worker, art-review |

New profiles are cloned from `developer` (writers) or `architect` (preparation), keeping `hermes_otel`, `factory-models`, the approvals floor and `dispatch_in_gateway: false`. Their models are switched to the values above.

## Art Director (prepare)

The Art Director writes `PLAN.md` with numbered acceptance criteria and an include list, following the factory-worker contract.

**Asset task:**
- **Bible check:** if `art/style/style.json` or `STYLE.md` is missing, or `art_lint` reports a bible BLOCKER, the Art Director completes `VERDICT=BLOCKED` with `blocked_reason: "no approved style bible: submit an Art task asking for a style bible"`. The controller stops the task for human review.
- **Asset list:** otherwise it lists each asset with:
  - target path, matching an existing `style.json` class;
  - kind (sprite or model);
  - a concept prompt;
  - the size, triangle or other class limits it must meet;
  - the STYLE rules it must satisfy.
- **Acceptance criteria:** one per asset, plus "art_lint reports no BLOCKER or HIGH".
- **Include list:** `art/style/` plus every target path, and for models the concept image path (`art/concepts/<name>.png`).

**Style task** (the prompt asks for a style bible, or no bible exists and the prompt is about style):
- The plan specifies the STYLE.md rules (with IDs and `(blocking)` marks), the `style.json` classes, the palette, and 2–3 reference images with prompts.
- The criteria require a valid bible (`art_lint` loads it) and the reference images.

## Artist (implement, repair)

The Artist works in PROJECT_DIR as a writer. Its `art-production` skill (installed at `~/.hermes/factory-skills/worker/art-production/`) provides:

- **`codex_image.sh <prompt-file> <out.png>`**
  - Runs `codex exec` non-interactively with the imagegen skill and writes one PNG.
  - Exit 0 only if `out.png` exists and decodes with `factory_art.png`.
  - Timeout 300 s.
- **`tripo_model.py <image.png> <out.glb>`**
  - Uploads the image to the Tripo API (`TRIPO_API_KEY` from the profile `.env`), creates an image-to-model task, polls at most every 5 s for up to 10 minutes, and downloads the GLB.
  - Exit 3 when no key is set, credits are exhausted, or the API is unavailable. That is the fallback signal.
  - Other failures exit 1. It never retries a charged task.
- **`blender_model.py`** (runs in Blender, through `blender_run.sh`) has two modes:
  - `cleanup <in.glb> <out.glb> --height <m> --origin bottom_center|center`: imports, applies transforms, scales to height, sets the origin, triangulates and exports GLB.
  - `blockout <concept.png> <out.glb> --height <m>`: the fallback. It builds a simple primitive-based model guided by a JSON spec the Artist writes after looking at the concept image, assigns colours sampled from the concept and the palette, and exports GLB.
- **Sprites:** Codex image → `sprite_fit.py <in.png> <out.png> --size WxH [--palette palette.gpl]`.
  - Removes a flat background to alpha, nearest-neighbour downscales to the class size, and quantizes to the palette when the class has one.
  - All standard library, reusing `factory_art.png`.

**Flow per asset:**
- Sprite: generate the concept, fit it, run `art_lint` on the file, and regenerate once if lint has BLOCKER or HIGH findings.
- Model: generate the concept, run Tripo (or blockout on exit 3), clean up, run `art_lint`.

**Completion metadata adds:**
- `assets`: `{path, kind, route: "tripo"|"blockout"|"codex", concept}`.
- `fallbacks`: reasons.
- `tripo_tasks`: IDs, so spend is traceable.

**Repair:** the Artist regenerates or refits only the assets named in the findings. It never edits `art/style/` in an asset task. A style task is the only kind allowed to write `art/style/`.

## Art type and Game Art template

`TASK_TYPES` becomes `('feature', 'bug', 'chore', 'art')`. Every enumeration listed under constraints accepts `art`. The intake and publish prefix maps use `ART`.

Game Art preset (seeded as a template plus type-default mapping by a one-off migration, because presets only seed on first initialization):

| Stage | Profile |
|---|---|
| Prepare | art-director |
| Implement | artist |
| Review | art-reviewer, claude-reviewer |
| Verify | verifier |
| Repair | artist, max 2 cycles |

Review instructions:
- **claude-reviewer:** reviews the changed scripts, JSON and import settings, not art taste.
- **art-reviewer:** follows the art-review skill.

Verify instructions add: run the art lint gate.

**Lint gate:** the Art Director's plan includes a `GATE` line, `GATE: art => python3 ~/.hermes/factory-skills/worker/art-review/scripts/art_lint.py "$SRC" --out "$WORK/art-lint"`. A gate fails when `lint_blocking` is true. To get that exit status, `art_lint.py` gains `--fail-on-blocking` (exit 1 when any BLOCKER or HIGH).

If GATE lines can only come from the root header (`factory_intake` / `repos.json`), the Game Art verify instructions carry the same command instead. The implementation plan confirms which mechanism applies before coding.

## Step 2: art-reviewer everywhere

`art-reviewer` gets the `review` capability. It is added to the dispatch roster, model catalog and defaults, so any template (for example Feature) may include it. With no art files in the manifest it completes `NO_BLOCKING_FINDINGS` with `art_surface: "none"`, as already implemented.

## Rollout and safety

1. Back up all of `~/.hermes` that this touches: `factory-dashboard/`, `plugins/factory-models/`, `config.yaml`, `state/factory/` (consistently, while no worker is running), and the profiles involved.
2. Build and test in a copy (`/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/`). Tests live in this repo under `tests/factory_art_type/` and import the copy.
3. Pause new claims, apply source edits, run the migration (roles, catalog, template, type default), re-bundle the plugin, and add profiles and roster entries. Then restart the gateway and confirm it is running.
4. Verify on a disposable board: an Art task captures the Game Art template and creates an art-director stage card with the expected profiles. No worker is launched.
5. One paid end-to-end Art task on a sample repo with its bible, with the user's go-ahead. One paid style task likewise.

**Rollback:** restore the backed-up source, plugin and config. Run the migration's reverse, which archives the Game Art template, removes the art type default, and leaves added role rows unused. Then restart the gateway. Existing tasks keep their frozen snapshots.

## Validation

- Unit tests for the edited Factory modules in the copy:
  - the capability map accepts the new profiles;
  - the `art` type passes every validator listed;
  - the preset validates and keeps writer/reviewer independence;
  - the migration is idempotent and reversible.
- Unit tests for `sprite_fit.py` (background removal, downscale, palette quantization) and for `tripo_model.py` against a local fake HTTP server: success, no key (exit 3), quota exhausted (exit 3), failed task, timeout.
- A Blender test for `cleanup` and `blockout` on the existing cube fixture.
- `codex_image.sh` is tested with a stub `codex` (no model). One real call during rollout step 5.

## Out of scope

Pausing a task mid-run for approval, sound, animation and rigging, in-engine capture, Tripo model variants and texturing options, automatic choice between multiple generations.
