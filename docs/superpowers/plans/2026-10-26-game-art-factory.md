# Game Art Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make game art a Factory product: an `art` task type with a default **Game Art** workflow (art-director prepares, artist produces through Codex image → Tripo image-to-3D → Blender cleanup with a Blender blockout fallback, art-reviewer + claude-reviewer review, verifier runs the art lint gate), and make `art-reviewer` selectable in any template.

**Architecture:** Part A lives in this repo and touches nothing under `~/.hermes`: a gate mode and a bible check for `scripts/art_lint.py`, a standard-library `art_production/` package (sprite fitting, Tripo v3 client), Blender and Codex wrappers, the `art-production` skill text, the two new profile souls and an installer. Part B edits a copy of the Factory (`/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/`, made with `cp -R`) and tests it from this repo (`tests/factory_art_type/`), plus a one-off migration (`scripts/migrate_game_art.py`) and a read-only install checker. Part C is the live rollout; every step that changes `~/.hermes` or spends money says **ASK THE USER FIRST**.

**Tech Stack:** Python 3.11+ standard library and unittest, POSIX sh, Blender 4.1 (`/Applications/Blender.app`), codex-cli 0.163.0 (`codex exec`), Tripo3D OpenAPI v3, Hermes CLI (only in Part C), sqlite3.

**Spec:** `docs/superpowers/specs/2026-10-26-game-art-factory-design.md`

**Git:** The user commits manually. Do not run `git add`/`git commit`; each task ends with a test run instead.

**Running tests:**
- Part A: `python3 -m unittest discover -s tests/art -p 'test_*.py' -v` and `python3 -m unittest discover -s tests/production -p 'test_*.py' -v`. Production tests import the art fixtures by bare name through `tests/production/production_fixtures.py`.
- Part B: `python3 -m unittest discover -s tests/factory_art_type -p 'test_*.py' -v`. It imports the Factory copy at `$HERMES_GAME_ART_COPY` (default `/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build`). Run it in its own process: `tests/ecc` imports the live `factory_dashboard` package.

---

## Decisions grounded in the installed code

These were checked against the live sources before writing the tasks. The tasks depend on them.

1. **GATE lines come only from the root header.** `~/.hermes/scripts/factory_intake.py:120-123` writes `GATE: <when> => <cmd>` lines from `repos.json` into the root header. `workflow_cards.build_stage_card` passes that header to every stage as `PROJECT CONSTRAINTS`, and `factory-worker/GATES.md` tells the verifier to run header GATE lines. Nothing parses GATE lines from `PLAN.md` or from a template. So the spec's fallback applies: the Game Art **verify instructions** (and implement/repair instructions, for the writer's own run) carry the lint gate command. The spec's `$SRC`/`$WORK` variables do not exist; the instructions name `<src_dir>` (from `fw.py snapshot`) and `$HERMES_KANBAN_WORKSPACE`. Instructions point at "art_lint.py from the art-review skill (the skill's LINT line gives its absolute path)" so no home path is hard-coded in the source.
2. **The bible check needs a bible-only mode.** `run_lint` reports a missing bible only when art files exist, so the art director cannot use it on an empty repo. Task 1 adds `art_lint.py --check-bible`.
3. **Prep `VERDICT=BLOCKED` stops the root in phase `blocked`** (`workflow_controller._writer` → `_stop(...,'blocked',...)`, task `blocked`/`needs_input`), not `human_review`. The effect the spec wants (stop, human sees the reason) is the same; a new task replaces it.
4. **Presets are code.** `WorkflowTemplates.initialize` seeds `_preset(kind)` for every `TASK_TYPES` entry, so `_preset('art')` must exist (fresh installs). The migration reuses `_preset('art')` from the installed source, so live and fresh templates are identical.
5. **Every captured role is validated against the catalog.** `serve_factory_dashboard.validate_roles` checks *all* default roles on each submission and the dashboard loads the catalog once at start. The migration writes catalog entries before role rows, and Part C restarts the dashboard (port 4610) as well as the gateway.
6. **Plugin bundling.** `bundle_factory_plugin.py` copies `integrations/hermes_factory_models/{plugin.yaml,__init__.py}`, which is not present under `~/.hermes/factory-dashboard`. The copy gets those two files from the installed `~/.hermes/plugins/factory-models/` (identical content, checked by Task 13). The bundle is installed in the root home **and in every profile home** (`~/.hermes/profiles/*/plugins/factory-models`, 13 today), so all must be swapped.
7. **Skills on cards.** Stage cards preload only `factory-worker` (`workflow_cards.py`). Profiles reach other skills through `skills.external_dirs` (`~/.hermes/factory-skills/worker`); the souls name the skill and its absolute path, as the art-reviewer soul already does.
8. **Secrets and HOME in worker terminals.** Terminal children get `HOME` redirected to the profile home and `HERMES_REAL_HOME` set (`hermes_constants.apply_subprocess_home_env`). `codex_image.sh` therefore uses `CODEX_HOME=${CODEX_HOME:-${HERMES_REAL_HOME:-$HOME}/.codex}`. Secrets pass to terminals only when not on the provider blocklist or when listed in `terminal.env_passthrough` (`tools/env_passthrough.py`); the artist profile lists `TRIPO_API_KEY` there.
9. **Branch and commit prefixes.** The spec's "prefix maps use ART" are, in the code, the intake branch prefix map and the publisher's conventional-commit type. Art jobs get branch `art/<slug>` and PR/commit title `feat(art): ...` (accepted by the publisher's title regex).
10. **Rollback cannot restore pre-art source while art rows exist.** Old code validates every template (archived too) with the old `TASK_TYPES`/`CAPABILITIES` in `WorkflowTemplates.list`, and every art snapshot in `get_snapshot`. So `--rollback` archives Game Art and removes the art default but the new source stays installed; `--rollback --purge-template` deletes the art template rows only when no snapshot used an art workflow and no other template uses an art profile. Only after a successful purge may the old source be restored.
11. **Pause mechanism.** `hermes pause` writes `$HERMES_HOME/ESTOP`; cron, kanban dispatch and new gateway turns stop, in-flight work continues; `hermes resume` removes it (`hermes_cli/subcommands/pause.py`). This is what earlier Factory rollouts used.
12. **Every `hermes` CLI call can finish a pending `hermes update` and stop the gateway.** Today `~/.hermes/logs/update.log` ends with "Update follow-up 'gateway_restart' did not finish". Part C checks for this before each `hermes` call and checks `~/.hermes/gateway_state.json` after.

### Tripo API (checked 2026-10-26)

Sources: https://developers.tripo3d.com/en/docs/files.md and the v2→v3 migration guide https://developers.tripo3d.com/assets/developer/tripo-v2-to-v3-migration/SKILL.md.

- Confirmed: base `https://openapi.tripo3d.com/v3`, `Authorization: Bearer <key>`; upload `POST /files` multipart field `file` → `{"code":0,"data":{"file_token":...}}`; generation `POST /generation/image-to-model` with `{"file":{"type":"png","file_token":...},"model_version":...}` (`model_version` required; values `v3.1-20260211`, `v3.0-20250812`, `v2.5-20250123`, `P1-20260311`); poll `GET /tasks/{task_id}`, statuses `queued`, `running`, `success`, `failed`, `cancelled` (unknown = failed), poll every 2-5 s; result `data.output.model_url`; failure `data.error_code`/`error_message`; auth failure HTTP 401 (code 2 or 1002); credits code 2010 (HTTP 403); rate limits 1007 and 2000; balance `GET /account/balance`.
- Assumed (isolated as constants in `art_production/tripo.py`, checked in Task 22): the balance response may or may not use the `data` envelope (both handled); error bodies carry `message`; `model_url` is a signed URL that needs no API key (the client never sends the key there); `v3.1-20260211` is the right default model version.

### codex exec (codex-cli 0.163.0, checked with `codex exec --help`, `codex features list`)

- Confirmed flags: `exec`, `--skip-git-repo-check`, `--ephemeral`, `--enable <feature>`, `-s workspace-write`, `-C <dir>`, `--color never`, `-o <file>`, `-m <model>`, prompt as the last argument. Feature `image_generation` is `stable true`. Built-in generations are stored as `~/.codex/generated_images/<thread>/exec-<uuid>.png` (seen on disk). The imagegen skill (`~/.codex/skills/.system/imagegen/SKILL.md`) says to use the built-in `image_gen` tool and copy the result into the workspace; `config.toml` has that skill entry `enabled = false`, which does not affect the built-in tool.
- Assumed (checked in Task 22 with one real call): the non-interactive agent calls `image_gen` and copies the file into `-C` under `workspace-write`; `--ephemeral` does not stop the image being saved; Codex PNGs are 8-bit non-interlaced (decodable by `factory_art.png`). If the copy step fails, the script falls back to the newest PNG written under `$CODEX_HOME/generated_images` after the start.

---

## File structure

```
scripts/art_lint.py                      modify: --fail-on-blocking (gate), --check-bible
art_production/
  __init__.py                            package docstring
  sprite_fit.py                          background to alpha, nearest-neighbour fit, palette quantize
  tripo.py                               Tripo v3 client; endpoints and codes as constants
  install/SKILL.md                       art-production skill text (installed)
  install/art-director.SOUL.md           art-director profile soul (installed)
  install/artist.SOUL.md                 artist profile soul (installed)
scripts/
  sprite_fit.py  check_png.py  tripo_model.py      CLIs (stdlib)
  codex_image.sh                         one Codex image, 300 s timeout
  blender_run.sh  blender_model.py       headless Blender cleanup / blockout
  install_art_production.sh              copy skill + packages into ~/.hermes/factory-skills/worker/art-production
  make_art_sample.py                     sample game with a bible for the paid runs
  migrate_game_art.py                    --dry-run / --apply / --rollback [--purge-template]
  check_game_art_install.py              read-only post-rollout check (no worker launched)
factory_game_art/
  __init__.py  migration.py              migration logic
tests/art/test_lint_cli.py
tests/production/
  production_fixtures.py  test_sprite_fit.py  test_tripo.py  test_codex_image.py
  test_blender_model.py  test_install.py  test_sample.py
tests/factory_art_type/
  factory_copy.py  test_copy.py  test_workflow_types.py  test_enumerations.py  test_scripts.py
  test_migration.py  test_bundle.py  test_check_install.py
artifacts/game-art-2026-10-26/           baseline checksums and patches (untracked)
docs/game-art-factory-results.md         rollout results and rollback
```

Factory files edited in the copy (Part B) and installed in Part C:

```
factory-dashboard/factory_dashboard/workflow_types.py      CAPABILITIES + TASK_TYPES
factory-dashboard/factory_dashboard/workflow_templates.py  GAME_ART notes + _preset('art')
factory-dashboard/factory_dashboard/task_submission.py     type check uses TASK_TYPES
factory-dashboard/factory_dashboard/assets/workflow_forms.js   type select
factory-dashboard/factory_dashboard/assets/task_forms.js       type select
scripts/factory_lib.py  scripts/factory_ticket.py  scripts/factory_intake.py  scripts/factory_publish.py
factory-skills/orchestrator/software-factory/SKILL.md      TYPE list for chat tickets
```

`scripts/factory_status.py` has no task-type enumeration and is not changed.

---

# Part A: this repository (no changes under ~/.hermes)

### Task 1: art_lint gate mode and bible check

**Files:**
- Modify: `scripts/art_lint.py`
- Test: `tests/art/test_lint_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/art/test_lint_cli.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from art_fixtures import build_testgame, sprite, write_bible
from factory_art.png import write_png

ROOT = Path(__file__).resolve().parents[2]
LINT = ROOT / 'scripts/art_lint.py'
CLEAN_CLASSES = [{'name': 'icon', 'kind': 'sprite', 'match': ['Assets/**'],
                  'size': {'width': [16, 64], 'height': [16, 64]}, 'alpha': 'required', 'rules': ['S1']}]


def lint(*args):
    return subprocess.run([sys.executable, str(LINT), *map(str, args)], capture_output=True, text=True)


class LintCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def clean_repo(self):
        repo = self.root / 'clean'
        write_bible(repo, CLEAN_CLASSES)
        (repo / 'Assets').mkdir()
        write_png(repo / 'Assets/hero.png', sprite())
        return repo

    def test_fail_on_blocking_exits_1_only_with_blocking_findings(self):
        game = build_testgame(self.root / 'game')
        plain = lint(game, '--out', self.root / 'a', '--blender', '/nonexistent')
        self.assertEqual(plain.returncode, 0, plain.stderr)
        gate = lint(game, '--out', self.root / 'b', '--blender', '/nonexistent', '--fail-on-blocking')
        self.assertEqual(gate.returncode, 1, gate.stderr)
        self.assertTrue(json.loads(gate.stdout)['lint_blocking'])
        clean = lint(self.clean_repo(), '--out', self.root / 'c', '--fail-on-blocking')
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertEqual(json.loads(clean.stdout)['findings'], 0)

    def test_art_without_a_bible_fails_the_gate(self):
        repo = self.root / 'nobible'
        (repo / 'Assets').mkdir(parents=True)
        write_png(repo / 'Assets/hero.png', sprite())
        self.assertEqual(lint(repo, '--out', self.root / 'd', '--fail-on-blocking').returncode, 1)

    def test_check_bible_reports_classes_or_the_error(self):
        ok = lint(build_testgame(self.root / 'game'), '--check-bible')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        data = json.loads(ok.stdout)
        self.assertEqual(data['bible'], 'ok')
        self.assertEqual(data['classes'], ['character_sprite', 'prop_model', 'ui_copy'])
        self.assertEqual(data['rules'], ['S1', 'S2', 'T1'])
        (self.root / 'empty').mkdir()
        bad = lint(self.root / 'empty', '--check-bible')
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(json.loads(bad.stdout)['bible'], 'invalid')
        self.assertIn('art/style/style.json not found', json.loads(bad.stdout)['error'])

    def test_out_is_required_without_check_bible(self):
        result = lint(self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--out is required', result.stderr)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/art -p 'test_lint_cli.py' -v`
Expected: 4 tests, FAILED: `unrecognized arguments: --fail-on-blocking` / `--check-bible` (argparse exit 2) and `the following arguments are required: --out` instead of `--out is required`.

- [ ] **Step 3: Implement**

Replace `scripts/art_lint.py` with:

```python
#!/usr/bin/env python3
"""Lint game art against the repo's art/style bible and prepare images for the vision review."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.blender_runner import find_blender
from factory_art.lint import run_lint
from factory_art.style_bible import BibleError, load_bible


def check_bible(repo):
    try:
        bible = load_bible(repo)
    except BibleError as error:
        print(json.dumps({'bible': 'invalid', 'error': str(error)}))
        return 1
    print(json.dumps({'bible': 'ok', 'classes': [cls['name'] for cls in bible['classes']],
                      'rules': sorted(bible['rules'])}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo')
    parser.add_argument('paths', nargs='*', help='files or directories relative to repo (default: all)')
    parser.add_argument('--out', help='directory for lint.json and review images (required unless --check-bible)')
    parser.add_argument('--first', action='append', default=[], help='review this file first (repeatable)')
    parser.add_argument('--max-images', type=int, default=40)
    parser.add_argument('--blender', help='Blender executable (default: $BLENDER, PATH, /Applications)')
    parser.add_argument('--timeout', type=int, default=120, help='seconds per model')
    parser.add_argument('--fail-on-blocking', action='store_true',
                        help='gate mode: exit 1 when any BLOCKER or HIGH finding exists')
    parser.add_argument('--check-bible', action='store_true',
                        help='only validate art/style: exit 0 when it loads, 1 when it does not')
    args = parser.parse_args()
    if args.check_bible:
        return check_bible(args.repo)
    if not args.out:
        parser.error('--out is required unless --check-bible is given')
    try:
        result = run_lint(args.repo, args.out, args.paths, find_blender(args.blender), args.first,
                          args.max_images, args.timeout)
    except ValueError as error:
        parser.exit(2, f'art_lint: {error}\n')
    summary = {key: result[key] for key in ('art_files', 'images', 'lint_blocking')}
    summary.update(findings=len(result['findings']), not_reviewed=len(result['not_reviewed']),
                   unverified=len(result['unverified']), lint=str(Path(args.out) / 'lint.json'))
    print(json.dumps(summary))
    return 1 if args.fail_on_blocking and result['lint_blocking'] else 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run the art suite**

Run: `python3 -m unittest discover -s tests/art -p 'test_*.py' -v`
Expected: 65 tests OK (61 existing + 4 new; the existing ones still exit 0 without the flag).

---

### Task 2: Sprite fitting

**Files:**
- Create: `art_production/__init__.py`, `art_production/sprite_fit.py`, `scripts/sprite_fit.py`, `scripts/check_png.py`
- Test: `tests/production/production_fixtures.py`, `tests/production/test_sprite_fit.py`

- [ ] **Step 1: Write the test helper and the failing test**

`tests/production/production_fixtures.py`:

```python
"""Shared paths for production tests: reuse the art test fixtures and import this repo's packages."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / 'tests' / 'art', ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
```

`tests/production/test_sprite_fit.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import PALETTE, gpl, sprite, upscale_pixels
from art_production.sprite_fit import downscale, fit, make_sprite, quantize, remove_background
from factory_art.png import Image, read_png, write_png
from factory_art.sprite_checks import check_sprite

WHITE, RED, CLEAR = (255, 255, 255, 255), (250, 10, 10, 255), (0, 0, 0, 0)


def canvas(width, height, rects):
    """White image with (left, top, width, height, colour) rectangles painted on it."""
    pixels = [WHITE] * (width * height)
    for left, top, w, h, colour in rects:
        for y in range(top, top + h):
            for x in range(left, left + w):
                pixels[y * width + x] = colour
    return Image(width, height, pixels)


class SpriteFitTests(unittest.TestCase):
    def test_background_connected_to_the_border_becomes_transparent(self):
        ring = canvas(8, 8, [(2, 2, 4, 4, RED), (3, 3, 2, 2, WHITE)])
        result = remove_background(ring)
        self.assertEqual(result.pixels[0], CLEAR)
        self.assertEqual(result.pixels[2 * 8 + 2], RED)
        self.assertEqual(result.pixels[3 * 8 + 3], WHITE)  # enclosed white is part of the sprite

    def test_images_with_alpha_keep_their_alpha(self):
        image = sprite(16)
        self.assertEqual(remove_background(image).pixels, image.pixels)

    def test_nearest_neighbour_downscale_recovers_an_upscaled_sprite(self):
        original = sprite(16, opaque=True)
        self.assertEqual(downscale(upscale_pixels(original, 4), 16, 16).pixels, original.pixels)

    def test_fit_keeps_aspect_ratio_and_centres_on_transparency(self):
        result = fit(remove_background(canvas(40, 20, [(10, 5, 20, 10, RED)])), 16, 16)
        self.assertEqual((result.width, result.height), (16, 16))
        rows = [result.pixels[y * 16:(y + 1) * 16] for y in range(16)]
        self.assertTrue(all(pixel == CLEAR for row in rows[:4] + rows[12:] for pixel in row))
        self.assertTrue(all(pixel == RED for row in rows[4:12] for pixel in row))

    def test_quantize_maps_visible_pixels_to_the_nearest_palette_colour(self):
        result = quantize(Image(2, 1, [RED, CLEAR]), PALETTE)
        self.assertEqual(result.pixels, [(200, 60, 60, 255), CLEAR])

    def test_fully_transparent_input_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'no visible pixels'):
            make_sprite(Image(4, 4, [CLEAR] * 16), 4, 4)

    def test_cli_output_passes_the_sprite_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_png(root / 'concept.png', canvas(64, 64, [(16, 8, 32, 48, RED), (24, 16, 16, 8, (40, 110, 210, 255))]))
            (root / 'palette.gpl').write_text(gpl(PALETTE))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_fit.py'), str(root / 'concept.png'),
                                     str(root / 'out/hero.png'), '--size', '32x32', '--palette', str(root / 'palette.gpl')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['palette'], 4)
            image = read_png(root / 'out/hero.png')
            cls = {'size': {'width': [32, 32], 'height': [32, 32]}, 'alpha': 'required', 'pixel_art': True,
                   'palette': {'file': 'palette.gpl', 'tolerance': 0}, '_palette': PALETTE}
            self.assertEqual(check_sprite('hero.png', image, cls), [])

    def test_cli_rejects_a_bad_size(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_fit.py'), 'a.png', 'b.png', '--size', '32'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('WIDTHxHEIGHT', result.stderr)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/production -p 'test_sprite_fit.py' -v`
Expected: ERROR `ModuleNotFoundError: No module named 'art_production'`

- [ ] **Step 3: Implement**

`art_production/__init__.py`:

```python
"""Game art production helpers for the Factory artist: sprite fitting and the Tripo image-to-3D client."""
```

`art_production/sprite_fit.py`:

```python
"""Turn a generated concept image into a game sprite: flat background to alpha, nearest-neighbour fit, palette."""
from collections import Counter, deque

from factory_art.png import Image

TRANSPARENT = (0, 0, 0, 0)


def remove_background(image, tolerance=24):
    """Make the flat background that touches the border transparent. Images with transparent corners are kept."""
    width, height, pixels = image.width, image.height, list(image.pixels)
    corners = [pixels[0], pixels[width - 1], pixels[(height - 1) * width], pixels[-1]]
    if any(pixel[3] < 255 for pixel in corners):
        return Image(width, height, [pixel if pixel[3] else TRANSPARENT for pixel in pixels])
    background = Counter(pixel[:3] for pixel in corners).most_common(1)[0][0]

    def near(pixel):
        return max(abs(a - b) for a, b in zip(pixel[:3], background)) <= tolerance

    border = set(range(width)) | {(height - 1) * width + x for x in range(width)}
    border |= {y * width for y in range(height)} | {y * width + width - 1 for y in range(height)}
    seen = bytearray(width * height)
    queue = deque(index for index in sorted(border) if near(pixels[index]))
    for index in queue:
        seen[index] = 1
    while queue:
        index = queue.popleft()
        pixels[index] = TRANSPARENT
        x, y = index % width, index // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                neighbour = ny * width + nx
                if not seen[neighbour] and near(pixels[neighbour]):
                    seen[neighbour] = 1
                    queue.append(neighbour)
    return Image(width, height, pixels)


def crop_to_content(image):
    visible = [index for index, pixel in enumerate(image.pixels) if pixel[3]]
    if not visible:
        raise ValueError('image has no visible pixels after background removal')
    xs = [index % image.width for index in visible]
    ys = [index // image.width for index in visible]
    left, right, top, bottom = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    return Image(right - left, bottom - top,
                 [image.pixels[y * image.width + x] for y in range(top, bottom) for x in range(left, right)])


def downscale(image, width, height):
    """Nearest-neighbour resample to exactly width x height, sampling the centre of each target pixel."""
    return Image(width, height, [
        image.pixels[min(image.height - 1, (2 * y + 1) * image.height // (2 * height)) * image.width
                     + min(image.width - 1, (2 * x + 1) * image.width // (2 * width))]
        for y in range(height) for x in range(width)])


def fit(image, width, height):
    """Scale the visible content uniformly to fit inside width x height, centred on a transparent canvas."""
    content = crop_to_content(image)
    scale = min(width / content.width, height / content.height)
    w = min(width, max(1, round(content.width * scale)))
    h = min(height, max(1, round(content.height * scale)))
    small = downscale(content, w, h)
    left, top = (width - w) // 2, (height - h) // 2
    pixels = [TRANSPARENT] * (width * height)
    for y in range(h):
        start = (top + y) * width + left
        pixels[start:start + w] = small.pixels[y * w:(y + 1) * w]
    return Image(width, height, pixels)


def harden_alpha(image, threshold=128):
    return Image(image.width, image.height,
                 [pixel[:3] + (255,) if pixel[3] >= threshold else TRANSPARENT for pixel in image.pixels])


def quantize(image, palette):
    """Map every visible pixel to the nearest palette colour (squared RGB distance)."""
    cache = {}

    def nearest(colour):
        if colour not in cache:
            cache[colour] = min(palette, key=lambda entry: sum((a - b) ** 2 for a, b in zip(colour, entry)))
        return cache[colour]

    return Image(image.width, image.height,
                 [nearest(pixel[:3]) + (pixel[3],) if pixel[3] else TRANSPARENT for pixel in image.pixels])


def make_sprite(image, width, height, palette=None, keep_background=False, tolerance=24):
    if not keep_background:
        image = remove_background(image, tolerance)
    sprite = harden_alpha(fit(image, width, height))
    return quantize(sprite, palette) if palette else sprite
```

`scripts/sprite_fit.py`:

```python
#!/usr/bin/env python3
"""Fit a generated image to a sprite class: flat background to alpha, nearest-neighbour fit, palette quantize."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from art_production.sprite_fit import make_sprite
from factory_art.png import PngError, read_png, write_png
from factory_art.style_bible import load_palette


def size(text):
    match = re.fullmatch(r'(\d+)x(\d+)', text)
    if not match or not all(int(value) > 0 for value in match.groups()):
        raise argparse.ArgumentTypeError('use WIDTHxHEIGHT, for example 32x32')
    return int(match[1]), int(match[2])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='generated PNG')
    parser.add_argument('out', help='sprite PNG to write')
    parser.add_argument('--size', type=size, required=True, help='class size, WIDTHxHEIGHT')
    parser.add_argument('--palette', help='GIMP .gpl palette from art/style (quantize to it)')
    parser.add_argument('--keep-background', action='store_true', help='do not turn the flat background into alpha')
    parser.add_argument('--tolerance', type=int, default=24, help='background colour tolerance per channel')
    args = parser.parse_args()
    try:
        palette = load_palette(args.palette) if args.palette else None
        if args.palette and not palette:
            raise ValueError(f'{args.palette} has no colours')
        sprite = make_sprite(read_png(args.source), *args.size, palette, args.keep_background, args.tolerance)
    except (OSError, ValueError) as error:
        parser.exit(1, f'sprite_fit: {error}\n')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_png(out, sprite)
    print(json.dumps({'out': str(out), 'width': sprite.width, 'height': sprite.height,
                      'transparent': sum(1 for pixel in sprite.pixels if not pixel[3]),
                      'palette': len(palette or [])}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

`scripts/check_png.py` (used by `codex_image.sh`):

```python
#!/usr/bin/env python3
"""Exit 0 and print the size when a file is a PNG that factory_art.png decodes; exit 1 otherwise."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.png import PngError, read_png


def main():
    if len(sys.argv) != 2:
        print('usage: check_png.py <file.png>', file=sys.stderr)
        return 2
    try:
        image = read_png(sys.argv[1])
    except (OSError, PngError) as error:
        print(f'check_png: {sys.argv[1]}: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'width': image.width, 'height': image.height}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

Run: `chmod +x scripts/sprite_fit.py scripts/check_png.py`

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/production -p 'test_sprite_fit.py' -v`
Expected: 8 tests OK

---

### Task 3: Tripo client and `tripo_model.py`

**Files:**
- Create: `art_production/tripo.py`, `scripts/tripo_model.py`
- Test: `tests/production/test_tripo.py` (local fake HTTP server; no network, no key, no spend)

- [ ] **Step 1: Write the failing test**

`tests/production/test_tripo.py`:

```python
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import cube, sprite
from art_production.tripo import MODEL_VERSION, FallbackError, TaskError, TripoClient, image_to_model
from factory_art.png import write_png


class FakeTripo:
    """Scripted local stand-in for the Tripo v3 API; task statuses are served in order, the last one repeats."""

    def __init__(self, statuses=('success',), create_error=None, glb=b''):
        self.requests, self.statuses, self.create_error, self.glb = [], list(statuses), create_error, glb
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, status, payload=None, raw=None):
                body = raw if raw is not None else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.requests.append(('GET', self.path, dict(self.headers), b''))
                if self.path == '/model.glb':
                    return self.reply(200, raw=fake.glb)
                if self.path == '/v3/account/balance':
                    return self.reply(200, {'code': 0, 'data': {'balance': 12.5, 'frozen': 0.0}})
                if self.path == '/v3/tasks/task-1':
                    status = fake.statuses.pop(0) if len(fake.statuses) > 1 else fake.statuses[0]
                    data = {'task_id': 'task-1', 'status': status}
                    if status == 'success':
                        data['output'] = {'model_url': fake.url + '/model.glb'}
                    if status == 'failed':
                        data.update(error_code=2008, error_message='moderation rejected')
                    return self.reply(200, {'code': 0, 'data': data})
                self.reply(404, {'code': 404, 'message': 'not found'})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                fake.requests.append(('POST', self.path, dict(self.headers), body))
                if self.path == '/v3/files':
                    return self.reply(200, {'code': 0, 'data': {'file_token': 'file_1'}})
                if self.path == '/v3/generation/image-to-model':
                    if fake.create_error:
                        return self.reply(*fake.create_error)
                    return self.reply(200, {'code': 0, 'data': {'task_id': 'task-1', 'status': 'queued'}})
                self.reply(404, {'code': 404, 'message': 'not found'})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def paths(self, method=None):
        return [path for verb, path, _, _ in self.requests if method in (None, verb)]


class TripoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.image = self.root / 'concept.png'
        write_png(self.image, sprite())
        cube(self.root / 'cube.glb')
        self.glb = (self.root / 'cube.glb').read_bytes()
        self.sleeps, self.now = [], 0.0

    def fake(self, **kwargs):
        kwargs.setdefault('glb', self.glb)
        fake = FakeTripo(**kwargs)
        self.addCleanup(fake.close)
        return fake

    def client(self, fake, key='secret-key'):
        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds
        return TripoClient(key, fake.url + '/v3', timeout=5, sleep=sleep, clock=lambda: self.now)

    def test_success_uploads_creates_polls_and_downloads_without_leaking_the_key(self):
        fake = self.fake(statuses=('queued', 'running', 'success'))
        client = self.client(fake)
        self.assertEqual(image_to_model(client, self.image, self.root / 'out/model.glb'), 'task-1')
        self.assertEqual((self.root / 'out/model.glb').read_bytes(), self.glb)
        self.assertEqual(fake.paths(), ['/v3/files', '/v3/generation/image-to-model', '/v3/tasks/task-1',
                                        '/v3/tasks/task-1', '/v3/tasks/task-1', '/model.glb'])
        self.assertEqual(self.sleeps, [5, 5])
        upload, create = fake.requests[0], fake.requests[1]
        self.assertIn(b'name="file"; filename="concept.png"', upload[3])
        self.assertIn(self.image.read_bytes(), upload[3])
        self.assertEqual(json.loads(create[3]), {'file': {'type': 'png', 'file_token': 'file_1'},
                                                 'model_version': MODEL_VERSION})
        self.assertTrue(all(r[2].get('Authorization') == 'Bearer secret-key' for r in fake.requests[:-1]))
        self.assertNotIn('Authorization', fake.requests[-1][2])
        self.assertEqual(client.task_ids, ['task-1'])

    def test_missing_key_is_a_fallback_before_any_request(self):
        fake = self.fake()
        with self.assertRaisesRegex(FallbackError, 'TRIPO_API_KEY'):
            self.client(fake, key='')
        self.assertEqual(fake.requests, [])

    def test_exhausted_credits_is_a_fallback_and_is_never_retried(self):
        fake = self.fake(create_error=(403, {'code': 2010, 'message': 'insufficient balance'}))
        with self.assertRaisesRegex(FallbackError, 'credits exhausted'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')
        self.assertEqual(fake.paths('POST').count('/v3/generation/image-to-model'), 1)

    def test_rejected_key_is_a_fallback(self):
        fake = self.fake(create_error=(401, {'code': 2, 'message': 'invalid key'}))
        with self.assertRaisesRegex(FallbackError, 'rejected the API key'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')

    def test_failed_task_is_an_error_and_is_not_created_again(self):
        fake = self.fake(statuses=('running', 'failed'))
        with self.assertRaisesRegex(TaskError, 'task-1 failed: 2008 moderation rejected'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')
        self.assertEqual(fake.paths('POST').count('/v3/generation/image-to-model'), 1)
        self.assertFalse((self.root / 'model.glb').exists())

    def test_task_times_out_after_ten_minutes_of_five_second_polls(self):
        fake = self.fake(statuses=('running',))
        with self.assertRaisesRegex(TaskError, 'timed out after 600s'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')
        self.assertEqual(len(self.sleeps), 120)
        self.assertEqual(set(self.sleeps), {5})

    def test_polling_is_never_faster_than_five_seconds(self):
        fake = self.fake(statuses=('running', 'success'))
        client = self.client(fake)
        client.wait('task-1', interval=1)
        self.assertEqual(self.sleeps, [5])

    def test_unreachable_api_is_a_fallback(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        client = TripoClient('secret-key', f'http://127.0.0.1:{port}/v3', timeout=5)
        with self.assertRaisesRegex(FallbackError, 'unavailable'):
            client.upload(self.image)

    def test_a_download_that_is_not_glb_is_an_error(self):
        fake = self.fake(glb=b'<html>expired</html>')
        with self.assertRaisesRegex(TaskError, 'not a GLB'):
            image_to_model(self.client(fake), self.image, self.root / 'model.glb')

    def run_cli(self, fake, *args, key='secret-key'):
        env = {k: v for k, v in os.environ.items() if k != 'TRIPO_API_KEY'}
        env['TRIPO_BASE_URL'] = fake.url + '/v3'
        if key:
            env['TRIPO_API_KEY'] = key
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/tripo_model.py'), *map(str, args)],
                                capture_output=True, text=True, env=env, timeout=60)
        return result.returncode, json.loads(result.stdout or '{}')

    def test_cli_exit_codes(self):
        out = self.root / 'cli.glb'
        self.assertEqual(self.run_cli(self.fake(), self.image, out, key='')[0], 3)
        code, data = self.run_cli(self.fake(create_error=(403, {'code': 2010})), self.image, out)
        self.assertEqual((code, data['tripo_tasks']), (3, []))
        (self.root / 'bad.png').write_bytes(b'not a png')
        fake = self.fake()
        self.assertEqual(self.run_cli(fake, self.root / 'bad.png', out)[0], 1)
        self.assertEqual(fake.requests, [])
        code, data = self.run_cli(self.fake(), self.image, out)
        self.assertEqual((code, data['task_id'], data['tripo_tasks']), (0, 'task-1', ['task-1']))
        self.assertEqual(out.read_bytes(), self.glb)
        self.assertEqual(self.run_cli(self.fake(), '--balance'), (0, {'balance': {'balance': 12.5, 'frozen': 0.0}}))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/production -p 'test_tripo.py' -v`
Expected: ERROR `ModuleNotFoundError: No module named 'art_production.tripo'`

- [ ] **Step 3: Implement**

`art_production/tripo.py`:

```python
"""Small Tripo3D OpenAPI v3 client: upload one image, run image-to-model, download the GLB.

Checked on 2026-10-26 against https://developers.tripo3d.com/en/docs/files.md (upload) and the v2 to v3 migration
guide https://developers.tripo3d.com/assets/developer/tripo-v2-to-v3-migration/SKILL.md (endpoints, statuses, codes).
Every endpoint, field and code is a constant here, so an API change is a one-line edit.
"""
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

BASE_URL = 'https://openapi.tripo3d.com/v3'
UPLOAD_PATH = '/files'
IMAGE_TO_MODEL_PATH = '/generation/image-to-model'
TASK_PATH = '/tasks/{task_id}'
BALANCE_PATH = '/account/balance'
MODEL_VERSION = 'v3.1-20260211'
AUTH_CODES = {2, 1002}
CREDIT_CODES = {2010}
BUSY_CODES = {1007, 2000}
RUNNING = {'queued', 'running'}
POLL_SECONDS = 5
LIMIT_SECONDS = 600
GET_RETRIES = 3


class FallbackError(RuntimeError):
    """No key, no credits, rejected key or API unavailable: the artist builds a Blender blockout (exit 3)."""


class TaskError(RuntimeError):
    """The request or the generation failed for another reason (exit 1)."""


def _json(raw):
    try:
        value = json.loads(raw or b'{}')
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


class TripoClient:
    def __init__(self, key, base_url=BASE_URL, timeout=60, sleep=time.sleep, clock=time.monotonic):
        if not key:
            raise FallbackError('TRIPO_API_KEY is not set')
        self.key, self.base_url, self.timeout = key, base_url.rstrip('/'), timeout
        self.sleep, self.clock = sleep, clock
        self.task_ids = []

    def _call(self, method, path, body=None, content_type=None, bare=False):
        headers = {'Authorization': f'Bearer {self.key}'}
        if content_type:
            headers['Content-Type'] = content_type
        request = urllib.request.Request(self.base_url + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload, status = _json(response.read()), response.status
        except urllib.error.HTTPError as error:
            payload, status = _json(error.read()), error.code
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FallbackError(f'Tripo API unavailable: {error}') from error
        code = payload.get('code', 0 if status < 400 else None)
        message = str(payload.get('message') or '')[:200]
        if status == 401 or code in AUTH_CODES:
            raise FallbackError(f'Tripo rejected the API key (HTTP {status}, code {code})')
        if code in CREDIT_CODES:
            raise FallbackError(f'Tripo credits exhausted (HTTP {status}, code {code})')
        if status >= 500 or code in BUSY_CODES:
            raise FallbackError(f'Tripo API unavailable (HTTP {status}, code {code}) {message}'.strip())
        if status >= 400 or code != 0:
            raise TaskError(f'Tripo {method} {path} failed (HTTP {status}, code {code}) {message}'.strip())
        data = payload.get('data', payload if bare else None)
        if not isinstance(data, dict):
            raise TaskError(f'Tripo {method} {path} returned no data object')
        return data

    def upload(self, image):
        image = Path(image)
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{image.name}"\r\n'
                'Content-Type: image/png\r\n\r\n').encode() + image.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        token = self._call('POST', UPLOAD_PATH, body, f'multipart/form-data; boundary={boundary}').get('file_token')
        if not isinstance(token, str) or not token:
            raise TaskError('Tripo upload returned no file_token')
        return token

    def create(self, file_token):
        body = json.dumps({'file': {'type': 'png', 'file_token': file_token}, 'model_version': MODEL_VERSION}).encode()
        task_id = self._call('POST', IMAGE_TO_MODEL_PATH, body, 'application/json').get('task_id')
        if not isinstance(task_id, str) or not task_id:
            raise TaskError('Tripo returned no task_id')
        self.task_ids.append(task_id)
        return task_id

    def wait(self, task_id, interval=POLL_SECONDS, limit=LIMIT_SECONDS):
        """Poll (never faster than every 5 s) until the task ends; return its model URL."""
        interval = max(interval, POLL_SECONDS)
        started, failures = self.clock(), 0
        while True:
            try:
                data = self._call('GET', TASK_PATH.format(task_id=task_id))
                failures = 0
            except FallbackError:
                failures += 1
                if failures >= GET_RETRIES:
                    raise
                data = {'status': 'running'}
            status = data.get('status')
            if status == 'success':
                url = (data.get('output') or {}).get('model_url')
                if not isinstance(url, str) or not url.startswith(('https://', 'http://')):
                    raise TaskError(f'Tripo task {task_id} succeeded without output.model_url')
                return url
            if status not in RUNNING:
                detail = f"{data.get('error_code', '')} {data.get('error_message') or ''}".strip()
                raise TaskError(f'Tripo task {task_id} {status}: {detail}'.strip())
            if self.clock() - started + interval > limit:
                raise TaskError(f'Tripo task {task_id} timed out after {limit}s')
            self.sleep(interval)

    def download(self, url, out):
        """Fetch the signed model URL without the API key and write the GLB atomically."""
        out = Path(out)
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=self.timeout) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TaskError(f'model download failed: {error}') from error
        if data[:4] != b'glTF':
            raise TaskError('downloaded model is not a GLB file')
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name(out.name + '.part')
        partial.write_bytes(data)
        partial.replace(out)
        return out

    def balance(self):
        return self._call('GET', BALANCE_PATH, bare=True)


def image_to_model(client, image, out, interval=POLL_SECONDS, limit=LIMIT_SECONDS):
    """One charged generation. Never retried: a failure after create() is reported with its task ID."""
    task_id = client.create(client.upload(image))
    client.download(client.wait(task_id, interval, limit), out)
    return task_id
```

`scripts/tripo_model.py`:

```python
#!/usr/bin/env python3
"""Image to GLB through the Tripo API. Exit 0 done, 1 failed, 2 usage, 3 fallback (no key, no credits, API down).

The key comes from TRIPO_API_KEY (the artist profile's .env). TRIPO_BASE_URL overrides the API root for tests.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from art_production.tripo import BASE_URL, FallbackError, TaskError, TripoClient, image_to_model
from factory_art.png import PngError, read_png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', nargs='?', help='concept PNG')
    parser.add_argument('out', nargs='?', help='GLB to write')
    parser.add_argument('--balance', action='store_true', help='print the account balance (free) and exit')
    args = parser.parse_args()
    if not args.balance and not (args.image and args.out):
        parser.error('image and out are required')
    client = None
    try:
        client = TripoClient(os.environ.get('TRIPO_API_KEY', '').strip(), os.environ.get('TRIPO_BASE_URL', BASE_URL))
        if args.balance:
            print(json.dumps({'balance': client.balance()}))
            return 0
        read_png(args.image)  # never pay for an image that does not decode
        task_id = image_to_model(client, args.image, args.out)
    except FallbackError as error:
        print(json.dumps({'fallback': str(error), 'tripo_tasks': client.task_ids if client else []}))
        return 3
    except (TaskError, OSError, PngError) as error:
        print(json.dumps({'error': str(error), 'tripo_tasks': client.task_ids if client else []}))
        return 1
    print(json.dumps({'model': args.out, 'task_id': task_id, 'tripo_tasks': client.task_ids}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

Run: `chmod +x scripts/tripo_model.py`

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/production -p 'test_tripo.py' -v`
Expected: 10 tests OK (about 7 s; the CLI test makes real local HTTP calls)

---

### Task 4: `codex_image.sh`

**Files:**
- Create: `scripts/codex_image.sh`
- Test: `tests/production/test_codex_image.py` (stub `codex`, no model call)

- [ ] **Step 1: Write the failing test**

`tests/production/test_codex_image.py`:

```python
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import sprite
from factory_art.png import read_png, write_png

STUB = f"""#!{sys.executable}
import json, os, pathlib, shutil, sys, time
args = sys.argv[1:]
pathlib.Path(os.environ['STUB_LOG']).write_text(json.dumps(args))
work = pathlib.Path(args[args.index('-C') + 1])
mode = os.environ['STUB_MODE']
if mode == 'copy':
    shutil.copy(os.environ['STUB_PNG'], work / 'image.png')
elif mode == 'home':
    target = pathlib.Path(os.environ['CODEX_HOME']) / 'generated_images' / 'thread-1'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(os.environ['STUB_PNG'], target / 'exec-new.png')
elif mode == 'garbage':
    (work / 'image.png').write_bytes(b'not a png')
elif mode == 'sleep':
    time.sleep(60)
sys.exit(int(os.environ.get('STUB_EXIT', '0')))
"""


class CodexImageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.stub = self.root / 'codex'
        self.stub.write_text(STUB)
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IXUSR)
        self.png = self.root / 'generated.png'
        write_png(self.png, sprite(32))
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text('Use case: stylized-concept\nPrimary request: a red gem on a flat white background\n')
        self.out = self.root / 'art/concepts/gem.png'

    def run_script(self, mode, *args, **env):
        full = {k: v for k, v in os.environ.items() if k not in ('CODEX_HOME', 'HERMES_REAL_HOME')}
        full.update(CODEX_BIN=str(self.stub), CODEX_HOME=str(self.root / 'codex-home'), STUB_MODE=mode,
                    STUB_PNG=str(self.png), STUB_LOG=str(self.root / 'argv.json'))
        full.update(env)
        full = {k: v for k, v in full.items() if v is not None}
        args = args or (self.prompt, self.out)
        return subprocess.run(['sh', str(ROOT / 'scripts/codex_image.sh'), *map(str, args)],
                              capture_output=True, text=True, env=full, timeout=60)

    def argv(self):
        return json.loads((self.root / 'argv.json').read_text())

    def test_copies_the_generated_image_and_runs_codex_non_interactively(self):
        result = self.run_script('copy')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'width': 32, 'height': 32})
        self.assertEqual(read_png(self.out).pixels, sprite(32).pixels)
        argv = self.argv()
        self.assertEqual(argv[0], 'exec')
        for flag in ('--skip-git-repo-check', '--ephemeral', '--enable', 'image_generation', '-s', 'workspace-write'):
            self.assertIn(flag, argv)
        self.assertIn('a red gem on a flat white background', argv[-1])
        self.assertIn('image_gen', argv[-1])

    def test_falls_back_to_the_newest_image_codex_saved_after_the_start(self):
        old = self.root / 'codex-home/generated_images/old/exec-old.png'
        old.parent.mkdir(parents=True)
        write_png(old, sprite(16))
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        result = self.run_script('home')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'width': 32, 'height': 32})

    def test_codex_home_defaults_to_the_real_home_under_hermes(self):
        real = self.root / 'real-home'
        result = self.run_script('home', CODEX_HOME=None, HERMES_REAL_HOME=str(real))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((real / '.codex/generated_images/thread-1/exec-new.png').is_file())

    def test_undecodable_or_missing_images_fail_without_writing_out(self):
        for mode in ('garbage', 'none'):
            result = self.run_script(mode)
            self.assertEqual(result.returncode, 1, mode)
            self.assertFalse(self.out.exists(), mode)

    def test_timeout_stops_codex(self):
        started = time.time()
        result = self.run_script('sleep', CODEX_IMAGE_TIMEOUT='2')
        self.assertEqual(result.returncode, 1)
        self.assertIn('timed out after 2s', result.stderr)
        self.assertLess(time.time() - started, 30)

    def test_usage_and_missing_codex(self):
        self.assertEqual(self.run_script('copy', self.prompt).returncode, 2)
        self.assertEqual(self.run_script('copy', self.prompt, self.root / 'gem.jpg').returncode, 2)
        self.assertEqual(self.run_script('copy', CODEX_BIN=str(self.root / 'missing')).returncode, 4)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/production -p 'test_codex_image.py' -v`
Expected: 6 tests FAIL (`sh: .../scripts/codex_image.sh: No such file or directory`, return code 127)

- [ ] **Step 3: Implement**

`scripts/codex_image.sh`:

```sh
#!/bin/sh
# Generate one PNG with Codex's built-in image_gen tool through non-interactive `codex exec`.
# usage: codex_image.sh <prompt-file> <out.png>
# exit: 0 out.png written and decodes, 1 no image / bad image / timeout, 2 usage, 4 codex CLI not found
# env: CODEX_BIN (default codex), CODEX_HOME (default $HERMES_REAL_HOME/.codex, else $HOME/.codex),
#      CODEX_IMAGE_TIMEOUT seconds (default 300), CODEX_IMAGE_MODEL (optional -m)
set -u
usage() { echo "usage: codex_image.sh <prompt-file> <out.png>" >&2; exit 2; }
[ $# -eq 2 ] && [ -f "$1" ] || usage
case "$2" in *.png) ;; *) usage ;; esac
here=$(cd "$(dirname "$0")" && pwd)
out=$2
codex=${CODEX_BIN:-codex}
command -v "$codex" >/dev/null 2>&1 || { echo "codex_image: codex CLI not found ($codex)" >&2; exit 4; }
CODEX_HOME=${CODEX_HOME:-${HERMES_REAL_HOME:-$HOME}/.codex}
export CODEX_HOME
limit=${CODEX_IMAGE_TIMEOUT:-300}
work=$(mktemp -d "${TMPDIR:-/tmp}/codex-image.XXXXXX") || exit 1
trap 'rm -rf "$work"' EXIT
: > "$work/.started"
request="Use your built-in image_gen tool exactly once to create the image described below. Do not write code, do not use the imagegen CLI fallback and do not change any file except ./image.png.
When the image is generated, copy the generated PNG file to ./image.png in the current directory, then reply DONE.

$(cat "$1")"
set -- exec --skip-git-repo-check --ephemeral --enable image_generation -s workspace-write -C "$work" \
  --color never -o "$work/last-message.txt"
[ -z "${CODEX_IMAGE_MODEL:-}" ] || set -- "$@" -m "$CODEX_IMAGE_MODEL"
"$codex" "$@" "$request" > "$work/codex.log" 2>&1 &
child=$!
# Watchdog: polls once a second and stops the child after $limit seconds; it ends by itself with the child.
( elapsed=0
  while kill -0 "$child" 2>/dev/null; do
    if [ "$elapsed" -ge "$limit" ]; then
      kill -TERM "$child" 2>/dev/null; sleep 5; kill -KILL "$child" 2>/dev/null; break
    fi
    sleep 1; elapsed=$((elapsed + 1))
  done ) &
watcher=$!
wait "$child"
status=$?
wait "$watcher"
if [ "$status" -ge 128 ]; then
  echo "codex_image: codex timed out after ${limit}s" >&2
  tail -n 20 "$work/codex.log" >&2
  exit 1
fi
image="$work/image.png"
if [ ! -s "$image" ] && [ -d "$CODEX_HOME/generated_images" ]; then
  newest=$(find "$CODEX_HOME/generated_images" -type f -name '*.png' -newer "$work/.started" -exec ls -t {} + 2>/dev/null | head -n 1)
  [ -z "$newest" ] || image=$newest
fi
if [ ! -s "$image" ]; then
  echo "codex_image: codex exited $status without an image" >&2
  tail -n 20 "$work/codex.log" >&2
  exit 1
fi
python3 "$here/check_png.py" "$image" > /dev/null || { echo "codex_image: the generated file is not a decodable PNG" >&2; exit 1; }
mkdir -p "$(dirname "$out")" || exit 1
cp "$image" "$out.part" && mv "$out.part" "$out" || exit 1
python3 "$here/check_png.py" "$out"
```

Run: `chmod +x scripts/codex_image.sh`

The watchdog is a polling subshell rather than `sleep $limit & kill`: a killed subshell defers its TERM until a foreground `sleep` ends, which orphaned `sleep` processes and blocked `wait` for the whole timeout in an earlier version.

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/production -p 'test_codex_image.py' -v`
Expected: 6 tests OK (about 5 s)

Run: `ps -ef | grep -E '[s]leep [0-9]+$'`
Expected: no output (no orphaned watchdog sleeps)

---

### Task 5: Blender cleanup and blockout

**Files:**
- Create: `scripts/blender_run.sh`, `scripts/blender_model.py`
- Test: `tests/production/test_blender_model.py` (uses the existing `tests/art/art_fixtures` cube writer; skipped without Blender)

- [ ] **Step 1: Write the failing test**

`tests/production/test_blender_model.py`:

```python
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import PALETTE, gpl, write_glb
from factory_art.blender_runner import find_blender, render_model
from factory_art.model_checks import check_model
from factory_art.png import Image, write_png

CUBE_FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def run_model(*args, **env):
    return subprocess.run(['sh', str(ROOT / 'scripts/blender_run.sh'), *map(str, args)], capture_output=True,
                          text=True, env=dict(os.environ, **env), timeout=400)


class RunnerTests(unittest.TestCase):
    def test_usage_and_missing_blender(self):
        self.assertEqual(run_model('render', 'a.glb').returncode, 2)
        missing = run_model('cleanup', 'a.glb', 'b.glb', '--height', '1', BLENDER='/nonexistent/blender')
        self.assertEqual(missing.returncode, 4)
        self.assertIn('Blender not found', missing.stderr)


@unittest.skipUnless(find_blender(), 'Blender not installed: set BLENDER or install /Applications/Blender.app')
class BlenderModelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = {'BLENDER': find_blender()}

    def stats(self, glb):
        return render_model(find_blender(), glb, self.root / 'render' / glb.stem, 120)

    def offset_cube(self):
        """2 m tall cube floating 2 m up and 3 m to the side (glTF Y-up)."""
        source = self.root / 'offset.glb'
        positions = [(x + 3.0, y * 2.0 + 2.0, z) for x in (-0.5, 0.5) for y in (0.0, 1.0) for z in (-0.5, 0.5)]
        write_glb(source, positions, [i for a, b, c, d in CUBE_FACES for i in (a, b, c, a, c, d)])
        return source

    def test_cleanup_scales_to_height_with_a_bottom_centre_origin(self):
        out = self.root / 'clean.glb'
        result = run_model('cleanup', self.offset_cube(), out, '--height', '0.5', **self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['triangles'], 12)
        stats = self.stats(out)
        self.assertEqual(stats['triangles'], 12)
        self.assertAlmostEqual(stats['bbox_min'][2], 0.0, places=4)
        self.assertAlmostEqual(stats['bbox_max'][2], 0.5, places=4)
        self.assertAlmostEqual(stats['bbox_min'][0], -0.125, places=4)
        prop = {'triangles_max': 5000, 'height_m': [0.2, 2.0], 'origin': 'bottom_center'}
        self.assertEqual(check_model('clean.glb', stats, prop), [])

    def test_cleanup_with_a_centre_origin(self):
        out = self.root / 'centred.glb'
        result = run_model('cleanup', self.offset_cube(), out, '--height', '0.5', '--origin', 'center', **self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        stats = self.stats(out)
        self.assertAlmostEqual(stats['bbox_min'][2], -0.25, places=4)
        self.assertAlmostEqual(stats['bbox_max'][2], 0.25, places=4)

    def blockout(self, *extra):
        concept = self.root / 'concept.png'
        write_png(concept, Image(8, 8, [(255, 0, 0, 255)] * 32 + [(0, 0, 255, 255)] * 32))  # red top, blue bottom
        spec = self.root / 'parts.json'
        spec.write_text(json.dumps({'parts': [
            {'shape': 'cube', 'location': [0, 0, 0.5], 'size': [0.8, 0.6, 1.0], 'sample': [0.5, 0.75]},
            {'shape': 'sphere', 'location': [0, 0, 1.3], 'size': [0.6, 0.6, 0.6], 'sample': [0.5, 0.25]},
            {'shape': 'cone', 'location': [0, 0, 1.8], 'size': [0.3, 0.3, 0.4], 'rotation': [0, 0, 45],
             'colour': '#c83c3c'}]}))
        out = self.root / 'blockout.glb'
        return out, run_model('blockout', concept, out, '--height', '1.2', '--spec', spec, *extra, **self.env)

    def test_blockout_builds_coloured_primitives_from_the_spec(self):
        out, result = self.blockout()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['colours'], ['#0000ff', '#ff0000', '#c83c3c'])
        self.assertEqual(data['parts'], 3)
        stats = self.stats(out)
        self.assertEqual(stats['materials'], 3)
        self.assertAlmostEqual(stats['bbox_min'][2], 0.0, places=4)
        self.assertAlmostEqual(stats['bbox_max'][2], 1.2, places=4)

    def test_blockout_snaps_colours_to_the_palette(self):
        (self.root / 'palette.gpl').write_text(gpl(PALETTE))
        out, result = self.blockout('--palette', self.root / 'palette.gpl')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['colours'], ['#3c78c8', '#c83c3c'])
        self.assertEqual(self.stats(out)['materials'], 2)

    def test_a_bad_spec_fails_with_a_reason(self):
        concept = self.root / 'concept.png'
        write_png(concept, Image(2, 2, [(255, 0, 0, 255)] * 4))
        spec = self.root / 'bad.json'
        spec.write_text(json.dumps({'parts': [{'shape': 'torus', 'location': [0, 0, 0], 'size': [1, 1, 1]}]}))
        result = run_model('blockout', concept, self.root / 'bad.glb', '--height', '1', '--spec', spec, **self.env)
        self.assertEqual(result.returncode, 1)
        self.assertIn('part shape must be one of', result.stderr)
        self.assertFalse((self.root / 'bad.glb').exists())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/production -p 'test_blender_model.py' -v`
Expected: 6 tests FAIL (return code 127, `blender_run.sh: No such file or directory`)

- [ ] **Step 3: Implement**

`scripts/blender_run.sh`:

```sh
#!/bin/sh
# Run blender_model.py in headless Blender and print its one-line JSON result.
# usage: blender_run.sh cleanup <in.glb> <out.glb> --height <m> [--origin bottom_center|center]
#        blender_run.sh blockout <concept.png> <out.glb> --height <m> --spec <parts.json> [--palette <file.gpl>] [--origin ...]
# exit: 0 done, 1 failed or timed out, 2 usage, 4 Blender not found
# env: BLENDER (executable), BLENDER_TIMEOUT seconds (default 300)
set -u
here=$(cd "$(dirname "$0")" && pwd)
case "${1:-}" in cleanup|blockout) ;; *) echo "usage: blender_run.sh cleanup|blockout ..." >&2; exit 2 ;; esac
if [ -n "${BLENDER:-}" ]; then
  blender=$BLENDER
elif command -v blender >/dev/null 2>&1; then
  blender=$(command -v blender)
else
  blender=/Applications/Blender.app/Contents/MacOS/Blender
fi
[ -x "$blender" ] || { echo "blender_run: Blender not found ($blender); set BLENDER" >&2; exit 4; }
limit=${BLENDER_TIMEOUT:-300}
log=$(mktemp "${TMPDIR:-/tmp}/blender-run.XXXXXX") || exit 1
trap 'rm -f "$log"' EXIT
"$blender" -b --factory-startup --python-exit-code 1 -P "$here/blender_model.py" -- "$@" > "$log" 2>&1 &
child=$!
# Watchdog: polls once a second and stops the child after $limit seconds; it ends by itself with the child.
( elapsed=0
  while kill -0 "$child" 2>/dev/null; do
    if [ "$elapsed" -ge "$limit" ]; then
      kill -TERM "$child" 2>/dev/null; sleep 5; kill -KILL "$child" 2>/dev/null; break
    fi
    sleep 1; elapsed=$((elapsed + 1))
  done ) &
watcher=$!
wait "$child"
status=$?
wait "$watcher"
if [ "$status" -ge 128 ]; then
  echo "blender_run: Blender timed out after ${limit}s" >&2
  exit 1
fi
if [ "$status" -ne 0 ] || ! grep -q '^BLENDER_MODEL ' "$log"; then
  grep '^BLENDER_MODEL_ERROR ' "$log" >&2 || tail -n 20 "$log" >&2
  exit 1
fi
grep '^BLENDER_MODEL ' "$log" | tail -n 1 | sed 's/^BLENDER_MODEL //'
```

`scripts/blender_model.py` (runs inside Blender's Python, not the system Python):

```python
"""Run inside Blender through blender_run.sh.

  cleanup <in.glb> <out.glb> --height <m> [--origin bottom_center|center]
  blockout <concept.png> <out.glb> --height <m> --spec <parts.json> [--palette <file.gpl>] [--origin ...]

Both bake every transform into one mesh, scale it to --height (Blender Z), set the origin, triangulate and export
GLB. blockout first builds primitives from a JSON spec: {"parts": [{"shape": "cube|cylinder|sphere|cone",
"location": [x, y, z], "size": [x, y, z], "rotation": [deg, deg, deg], "colour": "#rrggbb" or "sample": [u, v]}]}
where sample reads the concept image at u (left to right) and v (top to bottom), both 0..1, and --palette snaps
every colour to the nearest palette entry. Prints 'BLENDER_MODEL {json}', or 'BLENDER_MODEL_ERROR ...' and exit 1.
"""
import argparse
import json
import math
from pathlib import Path
import re
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Vector

SHAPES = {
    'cube': lambda: bpy.ops.mesh.primitive_cube_add(size=1),
    'cylinder': lambda: bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.5, depth=1),
    'sphere': lambda: bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=0.5),
    'cone': lambda: bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.5, radius2=0, depth=1),
}
MAX_PARTS = 64


def reset():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)


def import_model(path):
    suffix = Path(path).suffix.lower()
    if suffix in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix == '.obj':
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        raise ValueError(f'unsupported model format {suffix}')


def select_only(objects):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = objects[0]


def bake_and_join(meshes):
    """Apply every object (and parent) transform into its own mesh data, drop other objects, join into one."""
    for obj in meshes:
        matrix = obj.matrix_world.copy()
        obj.data = obj.data.copy()
        obj.data.transform(matrix)
    for obj in meshes:
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
    for obj in [o for o in bpy.context.scene.objects if o.type != 'MESH']:
        bpy.data.objects.remove(obj)
    select_only(meshes)
    if len(meshes) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def finish(obj, height, origin, out):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    coords = [vertex.co.copy() for vertex in obj.data.vertices]
    if not coords:
        raise ValueError('model has no vertices')
    low = Vector([min(c[i] for c in coords) for i in range(3)])
    high = Vector([max(c[i] for c in coords) for i in range(3)])
    if high.z - low.z <= 1e-6:
        raise ValueError('model has no height')
    scale = height / (high.z - low.z)
    anchor = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2,
                     low.z if origin == 'bottom_center' else (low.z + high.z) / 2))
    obj.data.transform(Matrix.Scale(scale, 4) @ Matrix.Translation(-anchor))
    obj.data.update()
    obj.location = (0.0, 0.0, 0.0)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    select_only([obj])
    bpy.ops.export_scene.gltf(filepath=str(out), export_format='GLB', use_selection=True)
    return {'out': str(out), 'triangles': len(obj.data.polygons),
            'materials': len({slot.material.name for slot in obj.material_slots if slot.material}),
            'height_m': round(height, 4), 'origin': origin}


def cleanup(args):
    import_model(args.source)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        raise ValueError('no mesh objects after import')
    return finish(bake_and_join(meshes), args.height, args.origin, args.out)


def load_palette(path):
    colours = []
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
            colours.append(tuple(int(part) for part in parts[:3]))
    if not colours:
        raise ValueError(f'{path} has no colours')
    return colours


def sample(image, u, v):
    width, height = image.size
    x = min(width - 1, max(0, int(u * width)))
    y = min(height - 1, max(0, int((1 - v) * height)))  # Blender rows start at the bottom
    index = (y * width + x) * 4
    return tuple(round(channel * 255) for channel in image.pixels[index:index + 3])


def numbers(part, key, default=None, positive=False):
    value = part.get(key, default)
    if (not isinstance(value, list) or len(value) != 3
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
            or (positive and min(value) <= 0)):
        raise ValueError(f'part {key} must be three {"positive " if positive else ""}numbers')
    return [float(v) for v in value]


def colour_of(part, image, palette):
    if isinstance(part.get('colour'), str) and re.fullmatch(r'#[0-9a-fA-F]{6}', part['colour']):
        colour = tuple(int(part['colour'][i:i + 2], 16) for i in (1, 3, 5))
    elif isinstance(part.get('sample'), list) and len(part['sample']) == 2 and all(
            isinstance(v, (int, float)) and 0 <= v <= 1 for v in part['sample']):
        colour = sample(image, *part['sample'])
    else:
        raise ValueError('each part needs "colour": "#rrggbb" or "sample": [u, v] with values 0..1')
    if palette:
        colour = min(palette, key=lambda entry: sum((a - b) ** 2 for a, b in zip(colour, entry)))
    return colour


def linear(channel):
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def material_for(colour, cache):
    if colour not in cache:
        material = bpy.data.materials.new('c%02x%02x%02x' % colour)
        material.use_nodes = True
        rgba = (*[linear(c) for c in colour], 1.0)
        material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = rgba
        material.diffuse_color = rgba
        cache[colour] = material
    return cache[colour]


def check_shape(part):
    if not isinstance(part, dict) or part.get('shape') not in SHAPES:
        raise ValueError(f'part shape must be one of {", ".join(SHAPES)}')
    return part


def add_part(part, material):
    location, size = numbers(part, 'location'), numbers(part, 'size', positive=True)
    rotation = [math.radians(a) for a in numbers(part, 'rotation', [0, 0, 0])]
    SHAPES[part['shape']]()
    obj = bpy.context.view_layer.objects.active
    obj.location, obj.rotation_euler, obj.scale = location, rotation, size
    obj.data.materials.append(material)
    return obj


def blockout(args):
    spec = json.loads(Path(args.spec).read_text())
    parts = spec.get('parts') if isinstance(spec, dict) else None
    if not isinstance(parts, list) or not 0 < len(parts) <= MAX_PARTS:
        raise ValueError(f'spec needs "parts": a list of 1 to {MAX_PARTS} primitives')
    image = bpy.data.images.load(str(Path(args.concept).resolve()))
    palette = load_palette(args.palette) if args.palette else None
    cache = {}
    meshes = [add_part(part, material_for(colour_of(check_shape(part), image, palette), cache)) for part in parts]
    result = finish(bake_and_join(meshes), args.height, args.origin, args.out)
    result.update(parts=len(parts), colours=['#%02x%02x%02x' % colour for colour in cache])
    return result


def parse(argv):
    parser = argparse.ArgumentParser(prog='blender_model.py')
    modes = parser.add_subparsers(dest='mode', required=True)
    clean = modes.add_parser('cleanup')
    clean.add_argument('source')
    clean.add_argument('out')
    block = modes.add_parser('blockout')
    block.add_argument('concept')
    block.add_argument('out')
    block.add_argument('--spec', required=True)
    block.add_argument('--palette')
    for mode in (clean, block):
        mode.add_argument('--height', type=float, required=True)
        mode.add_argument('--origin', choices=('bottom_center', 'center'), default='bottom_center')
    args = parser.parse_args(argv)
    if args.height <= 0:
        parser.error('--height must be positive')
    return args


if __name__ == '__main__':
    try:
        arguments = parse(sys.argv[sys.argv.index('--') + 1:])
        reset()
        outcome = cleanup(arguments) if arguments.mode == 'cleanup' else blockout(arguments)
    except Exception as error:
        print(f'BLENDER_MODEL_ERROR {type(error).__name__}: {error}', flush=True)
        traceback.print_exc()
        sys.exit(1)
    print('BLENDER_MODEL ' + json.dumps(outcome), flush=True)
```

Run: `chmod +x scripts/blender_run.sh`

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/production -p 'test_blender_model.py' -v`
Expected: 6 tests OK (about 8 s with Blender 4.1.1; without Blender, 5 skipped and 1 OK)

---

### Task 6: art-production skill, profile souls and installer

**Files:**
- Create: `art_production/install/SKILL.md`, `art_production/install/art-director.SOUL.md`, `art_production/install/artist.SOUL.md`, `scripts/install_art_production.sh`
- Test: `tests/production/test_install.py`

- [ ] **Step 1: Write the failing test**

`tests/production/test_install.py`:

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import sprite
from factory_art.png import write_png


class InstallTests(unittest.TestCase):
    def test_installs_a_runnable_skill_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / 'skills'
            env = dict(os.environ, HERMES_FACTORY_SKILLS=str(skills))
            command = ['sh', str(ROOT / 'scripts/install_art_production.sh')]
            first = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            skill = skills / 'art-production'
            text = (skill / 'SKILL.md').read_text()
            self.assertTrue(text.startswith('---\nname: art-production\n'))
            self.assertIn(f'sh {skill}/scripts/codex_image.sh', text)
            self.assertIn(f'python3 {skills}/art-review/scripts/art_lint.py', text)
            for path in [skill / 'SKILL.md', *(skill / 'souls').glob('*.md')]:
                self.assertNotIn('${', path.read_text(), path)
            self.assertEqual(sorted(p.name for p in (skill / 'souls').iterdir()),
                             ['art-director.SOUL.md', 'artist.SOUL.md'])
            self.assertFalse(list(skill.rglob('__pycache__')))
            self.assertFalse((skill / 'art_production/install').exists())
            for name in ('sprite_fit.py', 'check_png.py', 'tripo_model.py', 'codex_image.sh', 'blender_run.sh'):
                self.assertTrue(os.access(skill / 'scripts' / name, os.X_OK), name)
            self.assertTrue((skill / 'scripts/blender_model.py').is_file())
            write_png(Path(temp) / 'in.png', sprite(32))
            fit = subprocess.run([sys.executable, str(skill / 'scripts/sprite_fit.py'), str(Path(temp) / 'in.png'),
                                  str(Path(temp) / 'out.png'), '--size', '16x16'], capture_output=True, text=True)
            self.assertEqual(fit.returncode, 0, fit.stderr)
            env_no_key = {k: v for k, v in os.environ.items() if k != 'TRIPO_API_KEY'}
            tripo = subprocess.run([sys.executable, str(skill / 'scripts/tripo_model.py'), str(Path(temp) / 'in.png'),
                                    str(Path(temp) / 'm.glb')], capture_output=True, text=True, env=env_no_key)
            self.assertEqual(tripo.returncode, 3, tripo.stderr)
            self.assertIn('TRIPO_API_KEY', json.loads(tripo.stdout)['fallback'])
            again = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(again.returncode, 1)
            self.assertIn('already exists', again.stderr)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/production -p 'test_install.py' -v`
Expected: FAIL (installer missing, return code 127)

- [ ] **Step 3: Write the skill and souls**

`art_production/install/SKILL.md` (`${HERMES_SKILL_DIR}` and `${ART_REVIEW_DIR}` are replaced with absolute paths by the installer):

````markdown
---
name: art-production
description: Procedure and scripts for the Factory artist - Codex concept images, sprite fitting, Tripo image-to-3D with a Blender blockout fallback, Blender cleanup, and the art lint gate.
---

# Art production

Tools (run each as its own terminal command, never through `bash -c` or a pipe):

- `IMAGE` = `sh ${HERMES_SKILL_DIR}/scripts/codex_image.sh <prompt-file> <out.png>`: one Codex image (up to 5 minutes). Exit 0 means `out.png` exists and decodes.
- `FIT` = `python3 ${HERMES_SKILL_DIR}/scripts/sprite_fit.py <in.png> <out.png> --size WxH [--palette <art/style/palette file>]`: flat background to alpha, nearest-neighbour fit to the class size, palette quantize.
- `TRIPO` = `python3 ${HERMES_SKILL_DIR}/scripts/tripo_model.py <concept.png> <out.glb>`: Tripo image-to-model, up to 10 minutes. Exit 0 done, 3 fallback (no key, no credits, API down), 1 failed. It prints JSON with `tripo_tasks`; copy those IDs into your metadata every time, including failures.
- `BLENDER` = `sh ${HERMES_SKILL_DIR}/scripts/blender_run.sh`:
  - `cleanup <in.glb> <out.glb> --height <m> --origin bottom_center|center`
  - `blockout <concept.png> <out.glb> --height <m> --spec <parts.json> [--palette <file.gpl>] [--origin ...]`
- `LINT` = `python3 ${ART_REVIEW_DIR}/scripts/art_lint.py <PROJECT_DIR> <changed art paths> --out <PROJECT_DIR>/.factory/tmp/art-lint --fail-on-blocking`: exit 1 means a BLOCKER or HIGH finding; read `lint.json` there.

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
   - Exit 1: do not call TRIPO again for this asset (a charged task is never retried). Use the blockout route and record the error.
3. `LINT` the model. Fix only what the finding names (height, origin, triangles, materials) with one more `cleanup` or `blockout` run.

Record `{"path": <target>, "kind": "model", "route": "tripo" or "blockout", "concept": "art/concepts/<name>.png"}`.

## Style task

Only when the plan is a style task: write `art/style/STYLE.md`, `art/style/style.json`, the palette file and the reference images exactly as the plan specifies (references with `IMAGE`, then `FIT` when the plan gives a size). Then run `python3 ${ART_REVIEW_DIR}/scripts/art_lint.py <PROJECT_DIR> --check-bible` and fix until it prints `"bible": "ok"`.

## Completion

- Run `LINT` on every changed art path. Record it in `checks_run`, and in `failed_checks` when it exits 1.
- Metadata adds `assets` (the records above), `fallbacks` (one short reason per fallback asset), `tripo_tasks` (every Tripo task ID from every TRIPO run).
- Add every target path and every `art/concepts/<name>.png` to `.factory/include.txt`; never add `.factory/tmp/`.

## Repair

Regenerate or refit only the assets named in SCOPE findings, by the same route. Never call TRIPO again for an asset that already has a Tripo task in this job unless the finding is about the concept itself; record any new task ID.

## Rules

- An asset task never writes `art/style/`. Only a style task does.
- Never edit lint or bible files to make lint pass. Never fake a route: `route` says how the file was really made.
- `TRIPO_API_KEY` reaches the script through the environment. Never print, read or copy `.env` files or the key.
````

`art_production/install/art-director.SOUL.md`:

````markdown
# Role

You are the factory art director. You PLAN game art; you never make it. PROJECT_DIR is read-only for you; you write only inside your own scratch workspace.

# Work

1. Read your card: request, PROJECT_MODE, PROJECT_DIR, user acceptance criteria. Read AGENTS.md, CLAUDE.md and README in PROJECT_DIR if they exist.
2. Bible check: run `python3 ${ART_REVIEW_DIR}/scripts/art_lint.py <PROJECT_DIR> --check-bible`. Read `art/style/STYLE.md` and `art/style/style.json` when it prints `"bible": "ok"`, and look at the reference images with `vision_analyze`.
3. Decide the kind of task:
   - **Style task**: the request asks for a style bible, or no valid bible exists and the request is about style.
   - **Asset task**: anything else. Without a valid bible, complete `VERDICT=BLOCKED` with `blocked_reason: "no approved style bible: submit an Art task asking for a style bible"` and stop.
4. Write `$HERMES_KANBAN_WORKSPACE/PLAN.md`: Requirements (the card's REQUEST and USER_ACCEPTANCE verbatim), Kind (style or asset), Plan, Manifest include list, Acceptance Criteria AC1..ACn, Risks/Unknowns.
   - Asset task: list every asset with target path (it must match an existing `style.json` class), kind (sprite or model), a concept prompt, the class limits it must meet (size, palette, triangles, height, origin) and the STYLE rule IDs it must satisfy. One AC per asset ("<path> exists, matches class <name> and satisfies S<n>..."), plus one AC "art_lint reports no BLOCKER or HIGH for the changed art". Include list: `art/style/`, every target path, and `art/concepts/<name>.png` for every model.
   - Style task: specify the STYLE.md rules with IDs (S1.. for art, T1.. for text) and `(blocking)` marks, the `style.json` classes (kind, match globs, limits, rules, references, palette), the palette colours, and 2-3 reference images with their prompts and paths under `art/style/reference/`. ACs: `art_lint.py --check-bible` prints `"bible": "ok"`, and each reference image exists. Include list: `art/style/`.
   - Every AC must be checkable headlessly by the verifier on a copy of the manifest.
5. Complete with PLAN.md in `kanban_complete(artifacts=[...])` and `ac_ids` in metadata.

# Always

- Follow the factory-worker contract preloaded on your card. If the "Factory worker contract" section is not in your system prompt, `kanban_block(reason="factory-worker contract missing")` and stop.
- Never generate images or models, never write into PROJECT_DIR, never change `art/style/` yourself.
- Never run Git or GitHub writes; approvals.deny blocks them. If a command returns BLOCKED, do not work around it; record it in blocked_tools.
- `write_file`/`patch` only with absolute paths under `$HERMES_KANBAN_WORKSPACE` (enforced by a hook).
````

`art_production/install/artist.SOUL.md`:

````markdown
# Role

You are the factory artist. You make the game art that PLAN.md lists, in PROJECT_DIR, with the art-production skill. You do not change the plan.

# Work

1. Read the art-production skill: `${HERMES_SKILL_DIR}/SKILL.md`. Follow it for every asset.
2. Read the attached PLAN.md, copy it to `.factory/PLAN.md`, write `.factory/include.txt` from its include list, and read `art/style/`.
3. Make each asset by its route: sprites are Codex images fitted with sprite_fit; models are a Codex concept, then Tripo (or a Blender blockout when Tripo exits 3 or fails), then Blender cleanup.
4. Run the art lint gate on everything you changed, then `fw.py manifest PROJECT_DIR`.
5. Complete with `ac_ids`, `changed_files`, `assets`, `fallbacks` and `tripo_tasks` in metadata.

# Repair (FIX card)

Regenerate or refit only the assets named in SCOPE findings. Keep everything else byte-identical.

# Always

- Follow the factory-worker contract preloaded on your card. If the "Factory worker contract" section is not in your system prompt, `kanban_block(reason="factory-worker contract missing")` and stop.
- An asset task never writes `art/style/`; only a style task (PLAN.md says Kind: style) does.
- Never retry a Tripo task that was created and charged. Record every Tripo task ID.
- Never open, print or copy `.env` files or API keys.
- Never run Git or GitHub writes; approvals.deny blocks them. If a command returns BLOCKED, do not work around it; record it in blocked_tools.
````

- [ ] **Step 4: Write the installer**

`scripts/install_art_production.sh`:

```sh
#!/bin/sh
# Install the art-production worker skill: skill text, art profile souls, factory_art + art_production, scripts.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
skills=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}
dest=$skills/art-production
if [ -e "$dest" ]; then
  echo "install_art_production: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts" "$dest/souls"
rsync -a --exclude __pycache__ --exclude install "$root/factory_art/" "$dest/factory_art/"
rsync -a --exclude __pycache__ --exclude install "$root/art_production/" "$dest/art_production/"
for name in sprite_fit.py check_png.py tripo_model.py blender_model.py codex_image.sh blender_run.sh; do
  cp "$root/scripts/$name" "$dest/scripts/$name"
done
chmod +x "$dest"/scripts/*
esc() { printf '%s' "$1" | sed 's/[|&\\]/\\&/g'; }
fill() {
  sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" -e "s|\${ART_REVIEW_DIR}|$(esc "$skills/art-review")|g" "$1" > "$2"
}
fill "$root/art_production/install/SKILL.md" "$dest/SKILL.md"
fill "$root/art_production/install/art-director.SOUL.md" "$dest/souls/art-director.SOUL.md"
fill "$root/art_production/install/artist.SOUL.md" "$dest/souls/artist.SOUL.md"
echo "installed $dest"
```

Run: `chmod +x scripts/install_art_production.sh`

- [ ] **Step 5: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/production -p 'test_install.py' -v`
Expected: 1 test OK

---

### Task 7: Sample game for the paid runs

**Files:**
- Create: `scripts/make_art_sample.py`
- Test: `tests/production/test_sample.py`

- [ ] **Step 1: Write the failing test**

`tests/production/test_sample.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT


class SampleTests(unittest.TestCase):
    def test_sample_has_a_valid_bible_and_refuses_a_non_empty_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'art-sample'
            made = subprocess.run([sys.executable, str(ROOT / 'scripts/make_art_sample.py'), str(folder)],
                                  capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            check = subprocess.run([sys.executable, str(ROOT / 'scripts/art_lint.py'), str(folder), '--check-bible'],
                                   capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stdout)
            self.assertEqual(json.loads(check.stdout)['classes'], ['item_sprite', 'prop_model'])
            again = subprocess.run([sys.executable, str(ROOT / 'scripts/make_art_sample.py'), str(folder)],
                                   capture_output=True, text=True)
            self.assertEqual(again.returncode, 1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/production -p 'test_sample.py' -v`
Expected: FAIL (`can't open file .../scripts/make_art_sample.py`, return code 2)

- [ ] **Step 3: Implement**

`scripts/make_art_sample.py`:

```python
#!/usr/bin/env python3
"""Create a plain-folder sample game with an approved style bible for the paid Game Art rollout runs."""
import argparse
import json
from pathlib import Path

PALETTE = [(24, 20, 37), (38, 92, 66), (99, 199, 77), (254, 231, 97), (247, 118, 34), (190, 74, 47),
           (234, 212, 170), (90, 105, 136), (139, 155, 180), (255, 255, 255)]
STYLE = """# Sample game style

Cosy top-down fantasy, chunky readable shapes, limited palette.

**S1** (blocking) Every character and item reads clearly at 1x zoom against grass and stone.
**S2** Light comes from the top left; shadows fall to the bottom right.
**S3** Outlines are one pixel, using the darkest palette colour.
**S4** Props are simple, low-poly shapes with flat colours from the palette and no photographic textures.
"""
CLASSES = [
    {'name': 'item_sprite', 'kind': 'sprite', 'match': ['Assets/Art/Items/**'],
     'size': {'width': [32, 32], 'height': [32, 32]}, 'alpha': 'required', 'pixel_art': True,
     'palette': {'file': 'palette.gpl', 'tolerance': 0}, 'rules': ['S1', 'S2', 'S3']},
    {'name': 'prop_model', 'kind': 'model', 'match': ['Assets/Models/Props/**'], 'triangles_max': 3000,
     'materials_max': 4, 'texture_max_px': 512, 'height_m': [0.3, 1.5], 'origin': 'bottom_center',
     'rules': ['S2', 'S4']},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='new or empty folder')
    folder = parser.parse_args().folder
    if folder.exists() and any(folder.iterdir()):
        parser.exit(1, f'make_art_sample: {folder} is not empty\n')
    style = folder / 'art/style'
    style.mkdir(parents=True)
    (style / 'STYLE.md').write_text(STYLE)
    (style / 'style.json').write_text(json.dumps({'version': 1, 'classes': CLASSES}, indent=2) + '\n')
    (style / 'palette.gpl').write_text('GIMP Palette\nName: sample\nColumns: 5\n#\n'
                                       + ''.join(f'{r} {g} {b}\tc{i}\n' for i, (r, g, b) in enumerate(PALETTE)))
    for path in ('Assets/Art/Items', 'Assets/Models/Props', 'art/concepts'):
        (folder / path).mkdir(parents=True)
        (folder / path / '.keep').write_text('')
    (folder / 'README.md').write_text('# Art sample\n\nSample game for Factory Game Art runs. The bible is in art/style.\n')
    print(folder.resolve())


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run Part A**

Run: `python3 -m unittest discover -s tests/production -p 'test_*.py' -v && python3 -m unittest discover -s tests/art -p 'test_*.py'`
Expected: production 31 tests OK (about 30 s), art 65 tests OK.

---

# Part B: the Factory change, built and tested in a copy

### Task 8: Build the copy and the test harness

**Files:**
- Create: `/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/` (copy), `artifacts/game-art-2026-10-26/baseline.sha256`
- Test: `tests/factory_art_type/factory_copy.py`, `tests/factory_art_type/test_copy.py`

- [ ] **Step 1: Make the copy (read-only for ~/.hermes)**

```sh
rm -rf /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build
mkdir -p /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-skills/worker /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-skills/orchestrator
cp -R ~/.hermes/factory-dashboard /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard
cp -R ~/.hermes/scripts /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/scripts
cp -R ~/.hermes/factory-skills/worker/factory-worker /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-skills/worker/
cp -R ~/.hermes/factory-skills/orchestrator/software-factory /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-skills/orchestrator/
mkdir -p /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/integrations/hermes_factory_models
cp ~/.hermes/plugins/factory-models/plugin.yaml ~/.hermes/plugins/factory-models/__init__.py \
  /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/integrations/hermes_factory_models/
find /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build -name __pycache__ -prune -exec rm -rf {} +
```

`factory-skills/worker/factory-worker` is copied because the copy's `scripts/tests/sandbox.py` finds `fw.py` relative to the scripts folder.

- [ ] **Step 2: Record the baseline of every file this change edits**

```sh
mkdir -p artifacts/game-art-2026-10-26
cd ~/.hermes && shasum -a 256 \
  factory-dashboard/factory_dashboard/workflow_types.py factory-dashboard/factory_dashboard/workflow_templates.py \
  factory-dashboard/factory_dashboard/task_submission.py factory-dashboard/factory_dashboard/assets/workflow_forms.js \
  factory-dashboard/factory_dashboard/assets/task_forms.js scripts/factory_lib.py scripts/factory_ticket.py \
  scripts/factory_intake.py scripts/factory_publish.py factory-skills/orchestrator/software-factory/SKILL.md \
  > /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/baseline.sha256
cd /Users/example/orca/projects/hermes && wc -l artifacts/game-art-2026-10-26/baseline.sha256
```

Expected: `10 artifacts/game-art-2026-10-26/baseline.sha256`. Task 16 refuses to install if the live files no longer match.

- [ ] **Step 3: Write the harness and its test**

`tests/factory_art_type/factory_copy.py`:

```python
"""Point imports at the Game Art build copy of the Factory, never at the live ~/.hermes install.

The copy defaults to artifacts/game-art-2026-10-26/build in this repo; set HERMES_GAME_ART_COPY to use another one. Run this suite in
its own process: tests/ecc imports the live factory_dashboard package.
"""
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
LIVE = Path.home() / '.hermes'
COPY = Path(os.environ.get('HERMES_GAME_ART_COPY', str(REPO / 'artifacts/game-art-2026-10-26/build'))).resolve()
DASHBOARD = COPY / 'factory-dashboard'
SCRIPTS = COPY / 'scripts'
SKILLS = COPY / 'factory-skills'

if COPY == LIVE.resolve() or LIVE.resolve() in COPY.parents:
    raise RuntimeError(f'{COPY} is inside the live Hermes home; use a copy')
if not (DASHBOARD / 'factory_dashboard' / 'workflow_types.py').is_file():
    raise RuntimeError(f'Factory copy missing at {COPY}: run the Task 7 copy commands first')
for path in (SCRIPTS / 'tests', SCRIPTS, DASHBOARD, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import factory_dashboard  # noqa: E402

if Path(factory_dashboard.__file__).resolve().parent != (DASHBOARD / 'factory_dashboard').resolve():
    raise RuntimeError(f'factory_dashboard was imported from {factory_dashboard.__file__}, not the copy')
```

`tests/factory_art_type/test_copy.py`:

```python
import unittest
from pathlib import Path

from factory_copy import COPY, DASHBOARD, LIVE
import factory_dashboard
import factory_lib


class CopyTests(unittest.TestCase):
    def test_imports_come_from_the_copy(self):
        self.assertTrue(Path(factory_dashboard.__file__).resolve().is_relative_to(DASHBOARD.resolve()))
        self.assertTrue(Path(factory_lib.__file__).resolve().is_relative_to(COPY))
        self.assertFalse(COPY.is_relative_to(LIVE.resolve()))

    def test_copy_has_the_plugin_sources_for_bundling(self):
        plugin = DASHBOARD / 'integrations/hermes_factory_models'
        self.assertTrue((plugin / 'plugin.yaml').is_file())
        self.assertTrue((plugin / '__init__.py').is_file())
        self.assertTrue((COPY / 'factory-skills/worker/factory-worker/scripts/fw.py').is_file())
```

- [ ] **Step 4: Run it**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_copy.py' -v`
Expected: 2 tests OK

Run: `cd /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/scripts && python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: `Ran 27 tests` … `OK` (the copy's own script tests, unchanged baseline)

---

### Task 9: Capabilities, the art type and the Game Art preset

**Files:**
- Modify (copy): `/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/factory_dashboard/workflow_types.py`, `.../workflow_templates.py`
- Test: `tests/factory_art_type/test_workflow_types.py`

- [ ] **Step 1: Write the failing test**

`tests/factory_art_type/test_workflow_types.py`:

```python
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import factory_copy  # noqa: F401
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_templates import WorkflowTemplates, _preset
from factory_dashboard.workflow_types import CAPABILITIES, TASK_TYPES, WorkflowDefinition


def definition(kind):
    return WorkflowDefinition.from_document(_preset(kind))


class CapabilityTests(unittest.TestCase):
    def test_new_profiles_have_their_capabilities(self):
        self.assertEqual(CAPABILITIES['art-director'], ('prepare',))
        self.assertEqual(CAPABILITIES['artist'], ('implement', 'repair'))
        self.assertEqual(CAPABILITIES['art-reviewer'], ('review',))
        self.assertEqual(TASK_TYPES, ('feature', 'bug', 'chore', 'art'))

    def test_art_reviewer_can_join_any_template(self):
        doc = _preset('feature')
        doc['reviewers'].append(dict(key='art-reviewer', kind='review', profile='art-reviewer', instructions=''))
        self.assertIn('art-reviewer', [s.profile for s in WorkflowDefinition.from_document(doc).reviewers])

    def test_profiles_cannot_take_stages_outside_their_capability(self):
        for field, profile in (('implement', 'art-director'), ('prepare', 'artist'), ('verify', 'art-reviewer')):
            doc = _preset('art')
            doc[field] = dict(doc[field], profile=profile)
            with self.assertRaises(ConfigurationError, msg=field):
                WorkflowDefinition.from_document(doc)
        doc = _preset('art')
        doc['reviewers'].append(dict(key='artist', kind='review', profile='artist', instructions=''))
        with self.assertRaises(ConfigurationError):
            WorkflowDefinition.from_document(doc)


class GameArtPresetTests(unittest.TestCase):
    def test_game_art_preset_shape(self):
        art = definition('art')
        self.assertEqual((art.name, art.task_type, art.max_repairs), ('Game Art', 'art', 2))
        self.assertEqual((art.prepare.profile, art.implement.profile, art.repair.profile, art.verify.profile),
                         ('art-director', 'artist', 'artist', 'verifier'))
        self.assertEqual([s.profile for s in art.reviewers], ['art-reviewer', 'claude-reviewer'])
        self.assertIn('--fail-on-blocking', art.verify.instructions)
        self.assertIn('art_lint.py', art.verify.instructions)
        self.assertIn('--check-bible', art.prepare.instructions)
        self.assertIn('no approved style bible: submit an Art task asking for a style bible', art.prepare.instructions)
        self.assertIn('not judge art taste', art.reviewers[1].instructions)
        self.assertIn('art-review skill', art.reviewers[0].instructions)

    def test_writers_and_readers_stay_independent(self):
        art = definition('art')
        writers = {art.implement.profile, art.repair.profile}
        readers = {s.profile for s in art.reviewers} | {art.verify.profile}
        self.assertFalse(writers & readers)
        self.assertNotIn(art.prepare.profile, readers)

    def test_a_code_reviewer_is_still_required(self):
        doc = _preset('art')
        doc['reviewers'] = [r for r in doc['reviewers'] if r['profile'] != 'claude-reviewer']
        with self.assertRaisesRegex(ConfigurationError, 'code reviewer'):
            WorkflowDefinition.from_document(doc)

    def test_existing_presets_are_unchanged(self):
        chore = asdict(definition('chore'))
        chore.pop('template_id')
        stage = lambda key, profile, text='', kind=None: dict(key=key, kind=kind or key, profile=profile, instructions=text)
        self.assertEqual(chore, dict(
            revision=1, name='Chore', description='', task_type='chore',
            prepare=stage('prepare', 'developer', 'Define the scope and demonstrate no unintended behavior change.'),
            implement=stage('implement', 'developer'), reviewers=(stage('claude-reviewer', 'claude-reviewer', kind='review'),),
            verify=stage('verify', 'verifier'), repair=stage('repair', 'fixer'), max_repairs=3))
        self.assertEqual([s.profile for s in definition('feature').reviewers],
                         ['claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer'])
        self.assertEqual(definition('bug').repair.profile, 'fixer')

    def test_a_fresh_store_seeds_game_art_as_the_art_default(self):
        with tempfile.TemporaryDirectory() as temp:
            templates = WorkflowTemplates(TaskSettingsStore(Path(temp) / 'settings.db'))
            templates.initialize()
            mapping = templates.defaults()['templates']
            self.assertEqual(sorted(mapping), ['art', 'bug', 'chore', 'feature'])
            self.assertEqual(templates.get(mapping['art']).name, 'Game Art')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_workflow_types.py' -v`
Expected: 8 tests; ERRORs `KeyError: 'art-director'` and `KeyError: 'art'` (from `_preset`), FAIL on `TASK_TYPES` and on the fresh-store mapping. `test_existing_presets_are_unchanged` passes already.

- [ ] **Step 3: Edit `workflow_types.py` (copy)**

In `/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/factory_dashboard/workflow_types.py` replace:

```python
    'ui-reviewer': ('review',), 'verifier': ('verify',),
}
TASK_TYPES = ('feature', 'bug', 'chore')
```

with:

```python
    'ui-reviewer': ('review',), 'verifier': ('verify',),
    'art-director': ('prepare',), 'artist': ('implement', 'repair'), 'art-reviewer': ('review',),
}
TASK_TYPES = ('feature', 'bug', 'chore', 'art')
```

The reviewer rule (`at least one code reviewer`) is unchanged; Game Art satisfies it with `claude-reviewer`.

- [ ] **Step 4: Edit `workflow_templates.py` (copy)**

In `/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/factory_dashboard/workflow_templates.py` replace the whole `def _preset(kind):` function (from `def _preset(kind):` up to the blank lines before `class WorkflowTemplates:`) with:

```python
LINT = "art_lint.py from the art-review skill (the skill's LINT line gives its absolute path)"
GAME_ART = {
    'description': 'Art Director plans, Artist produces (Codex concept, Tripo or Blender blockout, Blender cleanup), art-reviewer and claude-reviewer review, verifier runs the art lint gate.',
    'prepare': ('Plan game art as the art-director SOUL says. First check the style bible: python3 <art_lint.py> <PROJECT_DIR> --check-bible, where art_lint.py is ' + LINT + '. '
                'Style task (the request asks for a style bible, or none exists and the request is about style): specify STYLE.md rules with IDs and (blocking) marks, style.json classes, the palette and 2-3 reference images with prompts; ACs require that --check-bible prints "bible": "ok" and that the references exist. '
                'Asset task without a valid bible: complete VERDICT=BLOCKED with blocked_reason "no approved style bible: submit an Art task asking for a style bible". '
                'Otherwise list every asset with target path (matching a style.json class), kind (sprite or model), concept prompt, class limits and STYLE rule IDs; one AC per asset plus "art_lint reports no BLOCKER or HIGH"; include list: art/style/, every target path and art/concepts/<name>.png for each model. '
                'For an asset task run python3 <art_lint.py> <PROJECT_DIR> --style-hash and record its value in PLAN.md as style_sha256: <hex>.'),
    'implement': ('Make the planned art with the art-production skill (artist SOUL). Before completing run the art lint gate on PROJECT_DIR: python3 <art_lint.py> <PROJECT_DIR> <changed art paths> --out <PROJECT_DIR>/.factory/tmp/art-lint --fail-on-blocking, where art_lint.py is ' + LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> in an asset task. '
                  'Record it in checks_run, and assets, fallbacks and tripo_tasks in metadata. An asset task never writes art/style/.'),
    'repair': 'Regenerate or refit only the assets named in SCOPE findings with the art-production skill, never art/style/ in an asset task, and rerun the art lint gate (with --expect-style-hash <style_sha256 from PLAN.md> in an asset task) before completing. Never call Tripo again for an asset with a recorded Tripo task or unknown-create; record new Tripo task IDs.',
    'verify': ('Run the art lint gate on the frozen copy as a required check: python3 <art_lint.py> <src_dir> --out "$HERMES_KANBAN_WORKSPACE/art-lint" --fail-on-blocking, where art_lint.py is ' + LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> when PLAN.md records one (asset task). '
               'Exit 1 means a BLOCKER or HIGH lint finding: record the command in failed_checks and fail the AC it threatens. Blender missing makes the affected model ACs unverified:environment. Attach art-lint/lint.json.'),
    'claude-reviewer': 'Review the changed scripts, JSON (style.json, text tables) and engine import settings (.meta files) for correctness. Do not judge art taste or style; art-reviewer does that.',
    'art-reviewer': 'Follow the art-review skill in factory mode.',
}


def _preset(kind):
    prepare, implement, reviewers = {
        'feature': ('architect', 'developer', ('claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer')),
        'bug': ('fixer', 'fixer', ('claude-reviewer', 'security-reviewer')),
        'chore': ('developer', 'developer', ('claude-reviewer',)),
        'art': ('art-director', 'artist', ('art-reviewer', 'claude-reviewer')),
    }[kind]
    def stage(key, profile, instructions='', stage_kind=None):
        return dict(key=key, kind=stage_kind or key, profile=profile, instructions=instructions)
    instructions = {'feature': 'Design the change and observable acceptance criteria.', 'bug': 'Diagnose the root cause and plan a regression test that fails before the repair and passes afterward.', 'chore': 'Define the scope and demonstrate no unintended behavior change.', 'art': GAME_ART['prepare']}
    notes = GAME_ART if kind == 'art' else {}
    return dict(template_id=str(uuid.uuid4()), revision=1, name={'feature':'Feature', 'bug':'Bug fix', 'chore':'Chore', 'art':'Game Art'}[kind], description=notes.get('description', ''), task_type=kind,
                prepare=stage('prepare', prepare, instructions[kind]), implement=stage('implement', implement, notes.get('implement', '')),
                reviewers=[stage(p, p, notes.get(p, ''), stage_kind='review') for p in reviewers], verify=stage('verify', 'verifier', notes.get('verify', '')),
                repair=stage('repair', 'artist' if kind == 'art' else 'fixer', notes.get('repair', '')), max_repairs=2 if kind == 'art' else 3)
```

The feature, bug and chore documents are byte-for-byte what the old function returned (`test_existing_presets_are_unchanged`).

- [ ] **Step 5: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_workflow_types.py' -v`
Expected: 8 tests OK

---

### Task 10: Every dashboard enumeration and the chat ticket instructions

**Files:**
- Modify (copy): `factory_dashboard/task_submission.py`, `factory_dashboard/assets/workflow_forms.js`, `factory_dashboard/assets/task_forms.js`, `factory-skills/orchestrator/software-factory/SKILL.md`
- Test: `tests/factory_art_type/test_enumerations.py`

- [ ] **Step 1: Write the failing test**

`tests/factory_art_type/test_enumerations.py`:

```python
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, SKILLS
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.task_settings import RoleSettings
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.task_submission import TaskSubmissionService
from factory_dashboard.workflow_capture import WorkflowCapture, intake_selection
from factory_dashboard.workflow_service import WorkflowService
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_dashboard.workflow_types import CAPABILITIES

ASSETS = DASHBOARD / 'factory_dashboard/assets'


class Projects:
    def list_projects(self):
        return [{'id': 'game', 'label': 'game'}]


def payload(kind):
    return dict(submission_id='0b0e5c1e-58a4-4c55-9df1-3f7c2c8b1f00', defaults_revision=1, title='Paint the hero',
                project='game', type=kind, prompt='Paint the hero sprite.', acceptance='')


class EnumerationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = TaskSettingsStore(Path(temp.name) / 'settings.db')
        self.templates = WorkflowTemplates(self.store)
        self.capture = WorkflowCapture(self.store, self.templates)
        self.capture.initialize()
        self.store.seed_defaults({p: RoleSettings('anthropic', 'claude-opus-5-5', 'high') for p in CAPABILITIES})

    def test_submission_accepts_art_and_rejects_unknown_types(self):
        service = TaskSubmissionService(self.store, Projects(), 'board', lambda roles: None)
        service._validate(payload('art'))
        with self.assertRaisesRegex(ConfigurationError, 'Invalid task type'):
            service._validate(payload('sound'))

    def test_art_tickets_select_the_game_art_workflow(self):
        body = 'FACTORY_TICKET v2\n' + json.dumps({'PROJECT': 'game', 'TYPE': 'art', 'ACCEPTANCE': '', 'REQUEST': 'x'})
        self.assertEqual(intake_selection({'body': body}), {'type': 'art'})
        self.assertEqual(self.capture.preview({'type': 'art'}).name, 'Game Art')
        with self.assertRaisesRegex(ConfigurationError, 'Unsupported task type'):
            self.capture.preview({'type': 'sound'})

    def test_captured_art_snapshot_freezes_the_game_art_definition(self):
        self.capture.set_enabled(True)
        snapshot = self.store.get_snapshot(
            self.store.capture_task('board', 't_art', 'direct_root', workflow_selection={'type': 'art'}))
        self.assertEqual(snapshot.workflow.implement.profile, 'artist')
        self.assertIn('art-director', snapshot.roles)

    def test_dashboard_lists_the_new_profiles(self):
        listing = WorkflowService(self.templates, self.capture, self.store, lambda: {'ready': True}).list()
        self.assertEqual(listing['capabilities']['artist'], ('implement', 'repair'))
        self.assertIn('art', listing['defaults']['templates'])

    def test_both_forms_offer_the_art_type(self):
        self.assertIn("doc.task_type,['feature','bug','chore','art'])", (ASSETS / 'workflow_forms.js').read_text())
        self.assertIn("options(type,['feature','bug','chore','art'].map(", (ASSETS / 'task_forms.js').read_text())

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_forms_still_parse(self):
        for name in ('workflow_forms.js', 'task_forms.js'):
            result = subprocess.run(['node', '--check', str(ASSETS / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_orchestrator_skill_names_the_art_type(self):
        text = (SKILLS / 'orchestrator/software-factory/SKILL.md').read_text()
        self.assertIn('`TYPE: feature|bug|chore|art`', text)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_enumerations.py' -v`
Expected: 7 tests; FAIL `Invalid task type` for art in `test_submission_accepts_art_and_rejects_unknown_types`, FAIL in the two form tests and the orchestrator test. The capture, snapshot, listing and `node --check` tests pass already (they depend on Task 9 only).

- [ ] **Step 3: Edit the copy**

`/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/factory_dashboard/task_submission.py`:
- replace `from .policy_store import RevisionConflict` (first line containing it) with:

```python
from .policy_store import RevisionConflict
from .workflow_types import TASK_TYPES
```

- replace `if payload['type'] not in ('feature','bug','chore'):raise` with `if payload['type'] not in TASK_TYPES:raise`

`/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/factory_dashboard/assets/workflow_forms.js` line 38: replace `doc.task_type,['feature','bug','chore'])` with `doc.task_type,['feature','bug','chore','art'])`

`/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard/factory_dashboard/assets/task_forms.js` line 43: replace `options(type,['feature','bug','chore'].map(` with `options(type,['feature','bug','chore','art'].map(`

`/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-skills/orchestrator/software-factory/SKILL.md` line 36: replace `` `TYPE: feature|bug|chore` (infer from the request)`` with `` `TYPE: feature|bug|chore|art` (infer from the request; art = sprites, 3D models or a style bible)``

The workflow editor's profile selects need no edit: `allowedProfiles` reads `capabilities` from `/api/workflows`, which now includes the art profiles.

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_enumerations.py' -v`
Expected: 7 tests OK

---

### Task 11: Ticket, intake and publish scripts

**Files:**
- Modify (copy): `/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/scripts/factory_lib.py`, `factory_ticket.py`, `factory_intake.py`, `factory_publish.py`
- Test: `tests/factory_art_type/test_scripts.py`

- [ ] **Step 1: Write the failing test**

`tests/factory_art_type/test_scripts.py`:

```python
import json
import os
import subprocess
import sys
import unittest

from factory_copy import SCRIPTS
import factory_lib
import test_publish
from sandbox import Sandbox

ENV = dict(GIT_CONFIG_NOSYSTEM='1', GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.com',
           GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.com')


def ticket(kind):
    return 'FACTORY_TICKET v2\n' + json.dumps({'PROJECT': 'game', 'TYPE': kind, 'ACCEPTANCE': 'none',
                                              'REQUEST': 'Paint the hero sprite in the approved style.'})


class TicketTests(unittest.TestCase):
    def test_structured_tickets_accept_art_only(self):
        self.assertEqual(factory_lib.parse_ticket(ticket('art'))['TYPE'], 'art')
        with self.assertRaisesRegex(ValueError, 'Invalid Factory ticket type'):
            factory_lib.parse_ticket(ticket('sound'))

    def test_ticket_cli_offers_art(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'factory_ticket.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('{feature,bug,chore,art}', result.stdout)


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.cleanup)
        self.repo = os.path.realpath(os.path.join(self.sb.root, 'game'))
        self.git('init', '-q', '-b', 'main', self.repo)
        with open(os.path.join(self.repo, 'README.md'), 'w') as f:
            f.write('game\n')
        self.git('-C', self.repo, 'add', 'README.md')
        self.git('-C', self.repo, 'commit', '-q', '-m', 'init')
        self.sb.write_json(self.sb.repos_path, {'default': 'game', 'repos': {
            'game': {'path': self.repo, 'base': 'main', 'auto_pr': False}}})
        # The sandbox's fake hermes answers `create` without an id; intake needs one to complete the ticket.
        fake = os.path.join(self.sb.bin, 'hermes')
        os.rename(fake, fake + '-sandbox')
        with open(fake, 'w') as f:
            f.write('#!/bin/sh\ncase " $* " in *" create "*) cat > /dev/null; echo \'{"id": "t_root0001"}\';;\n'
                    '*) exec "$0-sandbox" "$@";; esac\n')
        os.chmod(fake, 0o755)

    def git(self, *args):
        subprocess.run(['git', *args], check=True, capture_output=True, text=True, env=dict(os.environ, **ENV))

    def test_art_ticket_gets_an_art_branch(self):
        self.sb.add_task('t_art00001', 'TICKET: Paint hero', 'triage', body=ticket('art'))
        result = self.sb.run('factory_intake.py', env=ENV)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ticket t_art00001 -> root', result.stdout)
        branches = subprocess.run(['git', '-C', self.repo, 'branch', '--list', 'art/*', '--format=%(refname:short)'], capture_output=True,
                                  text=True).stdout.split()
        self.assertEqual(branches, ['art/paint-hero'])


class PublishTests(unittest.TestCase):
    def test_art_jobs_publish_with_a_feat_art_title(self):
        base = test_publish.PublishTests('test_passing_writer_gate_opens_a_draft_pr_with_only_manifest_files')
        base.setUp()
        self.addCleanup(base.tearDown)
        root = base.sb.tasks[0]
        root['body'] = root['body'].replace('TYPE: feature', 'TYPE: art')
        base.register_repo('true')
        result = base.sb.run('factory_publish.py', env={'GIT_CONFIG_NOSYSTEM': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('| feat(art): say hello', result.stdout)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_scripts.py' -v`
Expected: 4 tests, all FAIL: `Invalid Factory ticket type` for art; `{feature,bug,chore}` without art; the intake run exits non-zero on the art ticket (`ValueError: Invalid Factory ticket type`); the publish title is `feat: say hello`.

- [ ] **Step 3: Edit the copy (each old string occurs exactly once)**

| File | Replace | With |
|---|---|---|
| `factory_lib.py` | `if fields["TYPE"] not in {"feature", "bug", "chore"}:` | `if fields["TYPE"] not in {"feature", "bug", "chore", "art"}:` |
| `factory_ticket.py` | `choices=["feature", "bug", "chore"])` | `choices=["feature", "bug", "chore", "art"])` |
| `factory_intake.py` | `prefix = {"bug": "fix", "chore": "chore"}.get(` | `prefix = {"bug": "fix", "chore": "chore", "art": "art"}.get(` |
| `factory_intake.py` | `# Readable names: branch = <type>/<slug> (feature/, fix/, chore/)` | `# Readable names: branch = <type>/<slug> (feature/, fix/, chore/, art/)` |
| `factory_publish.py` | `ctype = {"bug": "fix", "chore": "chore"}.get(hv(body, "TYPE").lower(), "feat")` | `ctype = {"bug": "fix", "chore": "chore", "art": "feat(art)"}.get(hv(body, "TYPE").lower(), "feat")` |
| `factory_publish.py` | `# Conventional-commit style PR/commit title: "feat: ...", "fix: ...", "chore: ..." (from the job's TYPE).` | `# Conventional-commit style PR/commit title: "feat: ...", "fix: ...", "chore: ...", "feat(art): ..." (from the job's TYPE).` |

The intake root header already copies `TYPE` verbatim (`"TYPE: " + (f.get("TYPE") or "feature")`), so `TYPE: art` reaches `intake_selection` without another edit.

- [ ] **Step 4: Run it to verify it passes, plus the copy's own suite**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_scripts.py' -v`
Expected: 4 tests OK

Run: `cd /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/scripts && python3 -m unittest discover -s tests 2>&1 | tail -3`
Expected: `Ran 27 tests` … `OK`

---

### Task 12: Migration (roles, catalog, template, type default) and rollback

**Files:**
- Create: `factory_game_art/__init__.py`, `factory_game_art/migration.py`, `scripts/migrate_game_art.py`
- Test: `tests/factory_art_type/test_migration.py` (temporary stores, plus a sqlite `.backup` copy of the live store; the live files are hashed before and after)

- [ ] **Step 1: Write the failing test**

`tests/factory_art_type/test_migration.py`:

```python
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, LIVE, REPO
from factory_dashboard.model_catalog import ModelCatalog
from factory_dashboard.model_policy import ConfigurationError, ModelSelection
from factory_dashboard.task_settings import RoleSettings
from factory_dashboard.task_settings_store import TaskSettingsStore, encode
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_game_art.migration import NEW_ROLES, Migration

OLD_ROLES = {
    'architect': ('anthropic', 'claude-opus-5-5', 'high'), 'claude-reviewer': ('anthropic', 'claude-opus-5-5', 'high'),
    'codex-reviewer': ('openai-codex', 'gpt-6-sol', 'high'), 'developer': ('openai-codex', 'gpt-6-luna', 'medium'),
    'factory-orchestrator': ('openai-codex', 'gpt-6-astra', 'medium'), 'fixer': ('anthropic', 'claude-opus-5-5', 'high'),
    'security-reviewer': ('openai-codex', 'gpt-6.1-sol', 'high'), 'ui-reviewer': ('copilot', 'gemini-3.1-pro-preview', 'high'),
    'ux-reviewer': ('anthropic', 'claude-fable-5-1', 'high'), 'verifier': ('anthropic', 'claude-sonnet-5', 'high'),
}
CHOICES = [('anthropic', 'claude-opus-5-5'), ('anthropic', 'claude-sonnet-5'), ('openai-codex', 'gpt-6-luna'),
           ('openai-codex', 'gpt-6-sol'), ('copilot', 'gpt-5-mini')]
MIGRATE = REPO / 'scripts/migrate_game_art.py'


def legacy_install(root):
    """A settings store and catalog shaped like the live install before this change (no art anywhere)."""
    store = TaskSettingsStore(root / 'settings.db')
    WorkflowCapture(store, WorkflowTemplates(store)).initialize()
    with store._connect() as conn:
        mapping = json.loads(conn.execute('SELECT templates FROM factory_workflow_defaults').fetchone()[0])
        art = mapping.pop('art')
        conn.execute('DELETE FROM factory_workflow_revisions WHERE template_id=?', (art,))
        conn.execute('DELETE FROM factory_workflow_templates WHERE id=?', (art,))
        conn.execute('UPDATE factory_workflow_defaults SET templates=?', (encode(mapping),))
    store.seed_defaults({role: RoleSettings(*value) for role, value in OLD_ROLES.items()})
    catalog = {'profiles': {role: {'default': {'provider': p, 'model': m},
                                   'models': [{'provider': p, 'model': m, 'compatible': True}]
                                   + [{'provider': cp, 'model': cm, 'compatible': True}
                                      for cp, cm in CHOICES if (cp, cm) != (p, m)]}
                            for role, (p, m, _) in OLD_ROLES.items()}}
    (root / 'catalog.json').write_text(json.dumps(catalog, indent=2))
    return store


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = legacy_install(self.root)
        self.templates = WorkflowTemplates(self.store)
        self.migration = Migration(DASHBOARD, self.root / 'settings.db', self.root / 'catalog.json')

    def test_preview_lists_everything_and_writes_nothing(self):
        before = (digest(self.root / 'settings.db'), digest(self.root / 'catalog.json'))
        self.assertEqual(self.migration.preview(), {
            'catalog_add': sorted(NEW_ROLES), 'roles_add': sorted(NEW_ROLES), 'defaults_revision': 1,
            'template': None, 'type_default': None})
        self.assertEqual((digest(self.root / 'settings.db'), digest(self.root / 'catalog.json')), before)

    def test_apply_adds_catalog_roles_template_and_default(self):
        heads = {doc['template_id']: doc['revision'] for doc in self.templates.list()}
        receipt = self.migration.apply()
        self.assertEqual(receipt['catalog_added'], sorted(NEW_ROLES))
        self.assertEqual(receipt['roles_added'], list(NEW_ROLES))
        self.assertEqual(receipt['defaults_revision'], 2)
        catalog = ModelCatalog.from_file(self.root / 'catalog.json')
        defaults = self.store.read_defaults()
        for role, settings in defaults.roles.items():
            catalog.validate(ModelSelection(settings.provider, settings.model), (role,))
        raw = json.loads((self.root / 'catalog.json').read_text())
        for role, settings in NEW_ROLES.items():
            self.assertEqual(defaults.roles[role], RoleSettings(**settings))
            self.assertNotIn('copilot', {item['provider'] for item in raw['profiles'][role]['models']})
        art = self.templates.get(receipt['template_created'])
        self.assertEqual((art.name, art.revision, art.implement.profile), ('Game Art', 1, 'artist'))
        self.assertEqual(self.templates.defaults()['templates']['art'], art.template_id)
        self.assertEqual({doc['template_id']: doc['revision'] for doc in self.templates.list()
                          if doc['task_type'] != 'art'}, heads)

    def test_apply_is_idempotent(self):
        first = self.migration.apply()
        catalog = digest(self.root / 'catalog.json')
        second = self.migration.apply()
        self.assertEqual((second['catalog_added'], second['roles_added'], second['template_created'],
                          second['type_default_set']), ([], [], None, None))
        self.assertEqual(second['defaults_revision'], first['defaults_revision'])
        self.assertEqual(digest(self.root / 'catalog.json'), catalog)
        self.assertEqual(len(self.templates.list()), 4)

    def test_art_tasks_capture_game_art_after_apply(self):
        self.migration.apply()
        capture = WorkflowCapture(self.store, self.templates)
        capture.set_enabled(True)
        snapshot = self.store.get_snapshot(
            self.store.capture_task('board', 't_art', 'direct_root', workflow_selection={'type': 'art'}))
        self.assertEqual(snapshot.workflow.name, 'Game Art')
        self.assertEqual(snapshot.roles['artist'], RoleSettings(**NEW_ROLES['artist']))

    def test_rollback_removes_the_default_archives_and_is_idempotent(self):
        receipt = self.migration.apply()
        result = self.migration.rollback()
        self.assertEqual(result['type_default_removed'], receipt['template_created'])
        self.assertEqual(result['archived'], [receipt['template_created']])
        self.assertNotIn('art', self.templates.defaults()['templates'])
        self.assertTrue(next(d for d in self.templates.list(True) if d['task_type'] == 'art')['archived'])
        with self.assertRaisesRegex(ConfigurationError, 'Unsupported task type'):
            WorkflowCapture(self.store, self.templates).preview({'type': 'art'})
        self.assertIn('artist', self.store.read_defaults().roles)
        self.assertEqual(self.migration.rollback(), {'schema': 'factory-game-art-rollback/v1',
                                                     'type_default_removed': None, 'archived': [], 'purged': []})

    def test_purge_deletes_unused_art_templates_only(self):
        self.migration.apply()
        result = self.migration.rollback(purge=True)
        self.assertEqual(result['purged'], result['archived'])
        self.assertEqual([d['task_type'] for d in self.templates.list(True)], ['feature', 'bug', 'chore'])

    def test_purge_is_refused_once_an_art_task_was_captured(self):
        self.migration.apply()
        capture = WorkflowCapture(self.store, self.templates)
        capture.set_enabled(True)
        self.store.capture_task('board', 't_art', 'direct_root', workflow_selection={'type': 'art'})
        with self.assertRaisesRegex(ValueError, 'snapshot uses an art workflow'):
            self.migration.rollback(purge=True)
        self.assertEqual(len(self.templates.list(True)), 4)

    def test_cli_requires_a_new_receipt_and_rejects_pre_art_source(self):
        args = [sys.executable, str(MIGRATE), '--dashboard-source', str(DASHBOARD), '--settings-db',
                str(self.root / 'settings.db'), '--catalog', str(self.root / 'catalog.json')]
        self.assertEqual(subprocess.run(args + ['--apply'], capture_output=True, text=True).returncode, 2)
        (self.root / 'old.json').write_text('{}')
        taken = subprocess.run(args + ['--apply', '--receipt', str(self.root / 'old.json')], capture_output=True, text=True)
        self.assertIn('already exists', taken.stderr)
        old = self.root / 'old-source/factory_dashboard'
        old.mkdir(parents=True)
        (old / '__init__.py').write_text('')
        (old / 'workflow_types.py').write_text("TASK_TYPES = ('feature', 'bug', 'chore')\nCAPABILITIES = {}\n")
        args[3] = str(old.parent)
        result = subprocess.run(args + ['--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('lacks the art task type', result.stderr)


@unittest.skipUnless((LIVE / 'state/factory/task-settings.db').is_file(), 'no live Factory settings store')
class LiveCopyTests(unittest.TestCase):
    """Runs the CLI on a sqlite .backup copy of the live store; the live files must not change."""

    def test_cli_round_trip_on_a_copy_of_the_live_store(self):
        live_db, live_catalog = LIVE / 'state/factory/task-settings.db', LIVE / 'state/factory/model-catalog.json'
        before = (digest(live_db), digest(live_catalog))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = sqlite3.connect(f'file:{live_db}?mode=ro', uri=True)
            target = sqlite3.connect(root / 'settings.db')
            source.backup(target)
            target.close()
            source.close()
            (root / 'catalog.json').write_text(live_catalog.read_text())
            base = [sys.executable, str(MIGRATE), '--dashboard-source', str(DASHBOARD), '--settings-db',
                    str(root / 'settings.db'), '--catalog', str(root / 'catalog.json')]
            dry = subprocess.run(base + ['--dry-run'], capture_output=True, text=True)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertTrue(set(json.loads(dry.stdout)['roles_add']) <= set(NEW_ROLES))
            applied = subprocess.run(base + ['--apply', '--receipt', str(root / 'apply.json')], capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual((root / 'apply.json').stat().st_mode & 0o777, 0o600)
            after = json.loads(subprocess.run(base + ['--dry-run'], capture_output=True, text=True).stdout)
            self.assertEqual((after['catalog_add'], after['roles_add']), ([], []))
            self.assertIsNotNone(after['type_default'])
            self.assertEqual(after['template'], after['type_default'])
            back = subprocess.run(base + ['--rollback', '--receipt', str(root / 'rollback.json')], capture_output=True, text=True)
            self.assertEqual(back.returncode, 0, back.stderr)
            self.assertIsNone(json.loads(subprocess.run(base + ['--dry-run'], capture_output=True, text=True).stdout)['type_default'])
        self.assertEqual((digest(live_db), digest(live_catalog)), before)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_migration.py' -v`
Expected: ERROR `ModuleNotFoundError: No module named 'factory_game_art'`

- [ ] **Step 3: Implement**

`factory_game_art/__init__.py`:

```python
"""One-off Factory migration that adds the Game Art roles, catalog entries, template and art type default."""
```

`factory_game_art/migration.py`:

```python
"""Add the Game Art roles, catalog entries, template and art type default; reverse it. Every step is idempotent.

The dashboard source given to Migration must already contain the art task type and the three art profiles; the
template document itself comes from that source's _preset('art'), so the migration and fresh installs agree.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

NEW_ROLES = {
    'art-director': {'provider': 'anthropic', 'model': 'claude-opus-5-5', 'effort': 'high'},
    'artist': {'provider': 'openai-codex', 'model': 'gpt-6-luna', 'effort': 'medium'},
    'art-reviewer': {'provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'effort': 'high'},
}
CHOICES_FROM = {'art-director': 'architect', 'artist': 'developer', 'art-reviewer': 'verifier'}
ALLOWED_PROVIDERS = ('anthropic', 'openai-codex', 'openrouter')
TEMPLATE_NAME = 'Game Art'


def load_source(dashboard_source):
    source = Path(dashboard_source).resolve(strict=True)
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from factory_dashboard import workflow_types
    if not Path(workflow_types.__file__).resolve().is_relative_to(source):
        raise ValueError(f'factory_dashboard is already loaded from {workflow_types.__file__}, not {source}')
    if 'art' not in workflow_types.TASK_TYPES or not set(NEW_ROLES) <= set(workflow_types.CAPABILITIES):
        raise ValueError(f'{source} lacks the art task type and roles; install the Game Art source edits first')
    from factory_dashboard.model_catalog import ModelCatalog
    from factory_dashboard.task_settings import RoleSettings
    from factory_dashboard.task_settings_store import TaskSettingsStore, encode
    from factory_dashboard.workflow_templates import WorkflowTemplates, _preset
    return SimpleNamespace(ModelCatalog=ModelCatalog, RoleSettings=RoleSettings, TaskSettingsStore=TaskSettingsStore,
                           encode=encode, WorkflowTemplates=WorkflowTemplates, preset=_preset)


def catalog_changes(catalog):
    """Catalog entries for new roles: their default first, then the source role's choices minus Copilot."""
    changes = {}
    for role, settings in NEW_ROLES.items():
        if role in catalog['profiles']:
            continue
        default = {'provider': settings['provider'], 'model': settings['model']}
        source = catalog['profiles'].get(CHOICES_FROM[role], {}).get('models', [])
        models = [dict(default, compatible=True)] + [
            dict(item) for item in source
            if item.get('provider') in ALLOWED_PROVIDERS and (item['provider'], item['model']) != tuple(default.values())]
        changes[role] = {'default': default, 'models': models}
    return changes


def profiles(document):
    return ({document[key]['profile'] for key in ('prepare', 'implement', 'verify', 'repair')}
            | {stage['profile'] for stage in document['reviewers']})


def write_atomic(path, text):
    path = Path(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def write_receipt(path, result):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write('\n')


class Migration:
    def __init__(self, dashboard_source, settings_db, catalog_path):
        self.m = load_source(dashboard_source)
        self.store = self.m.TaskSettingsStore(settings_db, create=False)
        self.templates = self.m.WorkflowTemplates(self.store)
        self.catalog_path = Path(catalog_path)

    def _catalog(self):
        return json.loads(self.catalog_path.read_text())

    def _game_art(self):
        return [doc for doc in self.templates.list() if doc['task_type'] == 'art' and doc['name'] == TEMPLATE_NAME]

    def preview(self):
        defaults, mapping, existing = self.store.read_defaults(), self.templates.defaults(), self._game_art()
        return {'catalog_add': sorted(catalog_changes(self._catalog())),
                'roles_add': sorted(role for role in NEW_ROLES if role not in defaults.roles),
                'defaults_revision': defaults.revision,
                'template': existing[0]['template_id'] if existing else None,
                'type_default': mapping['templates'].get('art')}

    def apply(self):
        receipt = {'schema': 'factory-game-art-migration/v1', 'catalog_added': [], 'roles_added': [],
                   'template_created': None, 'type_default_set': None}
        # 1. Catalog first: the dashboard and the launch resolver validate every captured role against it.
        catalog = self._catalog()
        added = catalog_changes(catalog)
        if added:
            catalog['profiles'].update(added)
            self.m.ModelCatalog(catalog)
            write_atomic(self.catalog_path, json.dumps(catalog, indent=2) + '\n')
            receipt['catalog_added'] = sorted(added)
        # 2. Role defaults, in one revision (save_default rejects unknown roles, so this is the only way in).
        receipt['roles_added'] = self._add_roles()
        # 3. The template, from the source preset, then 4. the art type default.
        existing = self._game_art()
        if existing:
            template_id = existing[0]['template_id']
        else:
            document = self.m.preset('art')
            document.pop('template_id')
            document.pop('revision')
            template_id = self.templates.save(document, 0).template_id
            receipt['template_created'] = template_id
        mapping = self.templates.defaults()
        if 'art' not in mapping['templates']:
            self.templates.set_type_default('art', template_id, mapping['revision'])
            receipt['type_default_set'] = template_id
        receipt['defaults_revision'] = self.store.read_defaults().revision
        return receipt

    def _add_roles(self):
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT revision, roles FROM factory_defaults WHERE id=1').fetchone()
            roles = json.loads(row['roles'])
            if not roles:
                raise ValueError('Factory defaults are not initialized; run the settings migration first')
            added = [role for role in NEW_ROLES if role not in roles]
            for role in added:
                self.m.RoleSettings(**NEW_ROLES[role])
                roles[role] = dict(NEW_ROLES[role])
            if added:
                conn.execute('UPDATE factory_defaults SET revision=revision+1, roles=? WHERE id=1 AND revision=?',
                             (self.m.encode(roles), row['revision']))
            return added

    def rollback(self, purge=False):
        """Remove the art type default and archive Game Art. Role rows and catalog entries stay (unused)."""
        result = {'schema': 'factory-game-art-rollback/v1', 'type_default_removed': None, 'archived': [], 'purged': []}
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            mapping = self.templates.defaults(conn)
            if 'art' in mapping['templates']:
                templates = dict(mapping['templates'])
                result['type_default_removed'] = templates.pop('art')
                conn.execute('UPDATE factory_workflow_defaults SET revision=revision+1, templates=? WHERE id=1 AND revision=?',
                             (self.m.encode(templates), mapping['revision']))
        for document in self._game_art():
            self.templates.archive(document['template_id'], document['revision'])
            result['archived'].append(document['template_id'])
        if purge:
            result['purged'] = self._purge()
        return result

    def _purge(self):
        """Delete art template rows so pre-art source can load the template list again; refused once used."""
        with self.store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute('SELECT template_id, document FROM factory_workflow_revisions').fetchall()
            art = {row['template_id'] for row in rows if json.loads(row['document'])['task_type'] == 'art'}
            blockers = []
            for row in rows:
                document = json.loads(row['document'])
                used = profiles(document) & set(NEW_ROLES)
                if row['template_id'] not in art and used:
                    blockers.append(f"template {document['name']!r} revision {document['revision']} uses {sorted(used)}")
            if conn.execute('SELECT 1 FROM factory_snapshots WHERE document LIKE ? LIMIT 1',
                            ('%"task_type":"art"%',)).fetchone():
                blockers.append('a captured task snapshot uses an art workflow')
            if 'art' in self.templates.defaults(conn)['templates']:
                blockers.append('art is still a type default')
            if blockers:
                raise ValueError('cannot purge: ' + '; '.join(blockers))
            for template_id in sorted(art):
                conn.execute('DELETE FROM factory_workflow_revisions WHERE template_id=?', (template_id,))
                conn.execute('DELETE FROM factory_workflow_templates WHERE id=?', (template_id,))
            return sorted(art)
```

`scripts/migrate_game_art.py`:

```python
#!/usr/bin/env python3
"""Add the Game Art roles, catalog entries, template and art type default, or reverse it. Idempotent."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_game_art.migration import Migration, write_receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dashboard-source', required=True, type=Path,
                        help='factory-dashboard folder whose factory_dashboard package has the art type')
    parser.add_argument('--settings-db', required=True, type=Path, help='state/factory/task-settings.db')
    parser.add_argument('--catalog', required=True, type=Path, help='state/factory/model-catalog.json')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='print what --apply would change; write nothing')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true',
                      help='remove the art type default and archive Game Art; role rows and catalog entries stay')
    parser.add_argument('--purge-template', action='store_true',
                        help='with --rollback: delete the Game Art template rows (refused once any task used art)')
    parser.add_argument('--receipt', type=Path, help='new JSON file recording what --apply/--rollback changed')
    args = parser.parse_args()
    if (args.apply or args.rollback) and not args.receipt:
        parser.error('--apply and --rollback require a new --receipt path')
    if args.purge_template and not args.rollback:
        parser.error('--purge-template requires --rollback')
    if args.receipt and args.receipt.exists():
        parser.error(f'{args.receipt} already exists')
    try:
        migration = Migration(args.dashboard_source, args.settings_db, args.catalog)
        if args.dry_run:
            result = migration.preview()
        elif args.apply:
            result = migration.apply()
        else:
            result = migration.rollback(args.purge_template)
    except (ValueError, OSError) as error:
        parser.exit(2, f'migrate_game_art: {error}\n')
    if args.receipt:
        write_receipt(args.receipt, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

Run: `chmod +x scripts/migrate_game_art.py`

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_migration.py' -v`
Expected: 9 tests OK (the live-copy test is skipped only if `~/.hermes/state/factory/task-settings.db` is missing)

---

### Task 13: Bundle, install checker, full Part B run and patches

**Files:**
- Create: `scripts/check_game_art_install.py`, `artifacts/game-art-2026-10-26/*.patch`
- Test: `tests/factory_art_type/test_bundle.py`, `tests/factory_art_type/test_check_install.py`

- [ ] **Step 1: Write the failing tests**

`tests/factory_art_type/test_bundle.py`:

```python
import filecmp
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, LIVE

LIVE_PLUGIN = LIVE / 'plugins/factory-models'


class BundleTests(unittest.TestCase):
    def test_bundle_from_the_copy_carries_the_art_type(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'factory-models'
            result = subprocess.run([sys.executable, str(DASHBOARD / 'scripts/bundle_factory_plugin.py'), str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('workflow_types.py', 'workflow_templates.py', 'workflow_cards.py', 'workflow_controller.py'):
                self.assertTrue(filecmp.cmp(out / 'factory_dashboard' / name, DASHBOARD / 'factory_dashboard' / name,
                                            shallow=False), name)
            probe = subprocess.run([sys.executable, '-c', 'from factory_dashboard.workflow_types import TASK_TYPES, '
                                    'CAPABILITIES; print(TASK_TYPES[-1], CAPABILITIES["artist"])'],
                                   capture_output=True, text=True, cwd=out)
            self.assertEqual(probe.stdout.strip(), "art ('implement', 'repair')", probe.stderr)
            if LIVE_PLUGIN.is_dir():
                for name in ('plugin.yaml', '__init__.py'):
                    self.assertTrue(filecmp.cmp(out / name, LIVE_PLUGIN / name, shallow=False), name)
```

`tests/factory_art_type/test_check_install.py`:

```python
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, REPO
from test_migration import legacy_install
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_game_art.migration import Migration

PROFILE = """model:
  provider: {provider}
  default: {model}
platform_toolsets:
  cli:
    - kanban
    - file
    - terminal
    - vision
kanban:
  dispatch_in_gateway: false
"""
ROOT_CONFIG = """kanban:
  dispatch_profiles:
    - factory-orchestrator
    - verifier
    - claude-reviewer
{extra}code_execution:
  timeout: 300
"""


class CheckInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / 'hermes'
        state = self.home / 'state/factory'
        state.mkdir(parents=True)
        legacy_install(state)
        (state / 'settings.db').rename(state / 'task-settings.db')
        (state / 'catalog.json').rename(state / 'model-catalog.json')
        Migration(DASHBOARD, state / 'task-settings.db', state / 'model-catalog.json').apply()
        store = TaskSettingsStore(state / 'task-settings.db', create=False)
        WorkflowCapture(store, WorkflowTemplates(store)).set_enabled(True)  # as on the live install
        bundle = self.home / 'plugins/factory-models'
        subprocess.run([sys.executable, str(DASHBOARD / 'scripts/bundle_factory_plugin.py'), str(bundle)], check=True,
                       capture_output=True)
        for name, provider, model in (('art-director', 'anthropic', 'claude-opus-5-5'),
                                      ('artist', 'openai-codex', 'gpt-6-luna'),
                                      ('art-reviewer', 'anthropic', 'claude-sonnet-5-5')):
            folder = self.home / 'profiles' / name
            folder.mkdir(parents=True)
            (folder / 'config.yaml').write_text(PROFILE.format(provider=provider, model=model))
            (folder / 'SOUL.md').write_text('# Role\n')
            shutil.copytree(bundle, folder / 'plugins/factory-models')
        (self.home / 'config.yaml').write_text(ROOT_CONFIG.format(
            extra='    - art-director\n    - artist\n    - art-reviewer\n'))
        skills = self.home / 'factory-skills/worker'
        (skills / 'art-production').mkdir(parents=True)
        (skills / 'art-production/SKILL.md').write_text('---\nname: art-production\n---\n')
        (skills / 'art-review/scripts').mkdir(parents=True)
        shutil.copy(REPO / 'scripts/art_lint.py', skills / 'art-review/scripts/art_lint.py')

    def check(self):
        result = subprocess.run([sys.executable, str(REPO / 'scripts/check_game_art_install.py'), '--hermes-home',
                                 str(self.home)], capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def test_a_complete_install_passes_with_the_expected_cards(self):
        code, report = self.check()
        self.assertEqual(code, 0, report['problems'])
        self.assertEqual(report['cards']['prepare'], {'assignee': 'art-director', 'workspace': 'scratch',
                                                      'skills': ['factory-worker']})
        self.assertEqual(report['cards']['implement']['workspace'], 'dir')

    def test_problems_are_reported(self):
        (self.home / 'config.yaml').write_text(ROOT_CONFIG.format(extra=''))
        (self.home / 'profiles/artist/config.yaml').write_text(PROFILE.format(provider='copilot', model='x'))
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertIn('profile artist uses provider copilot', report['problems'])
        self.assertIn("root kanban.dispatch_profiles lacks ['art-director', 'art-reviewer', 'artist']", report['problems'])
```

- [ ] **Step 2: Run them**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_bundle.py' -v`
Expected: 1 test OK (bundling already works once Task 8 put the plugin files in the copy)

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_check_install.py' -v`
Expected: 2 tests FAIL (`can't open file .../scripts/check_game_art_install.py`, then `json.decoder.JSONDecodeError` on empty output)

- [ ] **Step 3: Implement the checker**

`scripts/check_game_art_install.py` (imports the **installed** plugin bundle; captures one art task on a private `.backup` copy of the settings store; builds every stage card; checks catalog, profiles, plugin copies, roster and skills; launches nothing):

```python
#!/usr/bin/env python3
"""Read-only check of an installed Game Art rollout. Never launches a worker and never writes to the Hermes home.

Imports the installed plugin bundle, captures an Art task on a private sqlite .backup copy of the settings store,
builds every stage card for it, and checks catalog, profiles, plugin copies, roster and skills. Exit 1 on problems.
"""
import argparse
import filecmp
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ART_PROFILES = ('art-director', 'artist', 'art-reviewer')
STAGES = {'prepare': ('art-director', 'scratch'), 'implement': ('artist', 'dir'), 'repair': ('artist', 'dir'),
          'art-reviewer': ('art-reviewer', 'scratch'), 'claude-reviewer': ('claude-reviewer', 'scratch'),
          'verify': ('verifier', 'scratch')}


def config_model(text):
    lines = text.splitlines()
    start = lines.index('model:')
    values = dict(line.strip().split(': ', 1) for line in lines[start + 1:start + 3])
    return values.get('provider'), values.get('default')


def roster(text):
    lines, names, inside = text.splitlines(), [], False
    for line in lines:
        if line.strip() == 'dispatch_profiles:':
            inside = True
        elif inside and line.strip().startswith('- '):
            names.append(line.strip()[2:])
        elif inside and line.strip() and not line.strip().startswith('#'):
            break
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-home', type=Path, default=Path.home() / '.hermes')
    home = parser.parse_args().hermes_home.resolve()
    bundle = home / 'plugins/factory-models'
    sys.path.insert(0, str(bundle))
    from factory_dashboard.model_catalog import ModelCatalog
    from factory_dashboard.model_policy import ModelSelection
    from factory_dashboard.task_settings_store import TaskSettingsStore
    from factory_dashboard.workflow_capture import WorkflowCapture
    from factory_dashboard.workflow_cards import build_stage_card
    from factory_dashboard.workflow_types import CAPABILITIES, TASK_TYPES
    problems, cards = [], {}
    if 'art' not in TASK_TYPES or not set(ART_PROFILES) <= set(CAPABILITIES):
        problems.append('installed plugin bundle lacks the art type or profiles')
    catalog = ModelCatalog.from_file(home / 'state/factory/model-catalog.json')
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / 'settings.db'
        source = sqlite3.connect(f"file:{home / 'state/factory/task-settings.db'}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        source.backup(target)
        target.close()
        source.close()
        store = TaskSettingsStore(copy, create=False)
        roles = store.read_defaults().roles
        for role, settings in roles.items():
            try:
                catalog.validate(ModelSelection(settings.provider, settings.model), (role,))
            except ValueError as error:
                problems.append(f'{role}: {error}')
        for role in ART_PROFILES:
            if role not in roles:
                problems.append(f'{role} has no Factory default')
            elif roles[role].provider not in ('anthropic', 'openai-codex', 'openrouter'):
                problems.append(f'{role} default provider {roles[role].provider} is not allowed')
        with store._connect() as conn:
            if not WorkflowCapture.enabled(conn):
                problems.append('workflow capture is disabled in the settings store')
                conn.execute('UPDATE factory_workflow_activation SET enabled=1 WHERE id=1')  # private copy only
        try:
            workflow = store.get_snapshot(store.capture_task(
                'game-art-check', 't_gameartcheck', 'direct_root', workflow_selection={'type': 'art'})).workflow
        except ValueError as error:
            problems.append(f'an art task cannot be captured: {error}')
            workflow = None
        if workflow is not None and workflow.name != 'Game Art':
            problems.append(f'an art task captured {workflow.name}, not Game Art')
        elif workflow is not None:
            for key, (profile, workspace) in STAGES.items():
                card = build_stage_card(workflow, key, 0, {'project_dir': '/tmp/game-art-check', 'root_id': 't_gameartcheck'}, [])
                cards[key] = {'assignee': card['assignee'], 'workspace': card['workspace_kind'], 'skills': card['skills']}
                if (card['assignee'], card['workspace_kind'], card['skills']) != (profile, workspace, ['factory-worker']):
                    problems.append(f'{key} card is {cards[key]}')
    homes = [home] + sorted(path for path in (home / 'profiles').iterdir() if (path / 'plugins/factory-models').is_dir())
    for other in homes[1:]:
        if not filecmp.cmp(other / 'plugins/factory-models/factory_dashboard/workflow_types.py',
                           bundle / 'factory_dashboard/workflow_types.py', shallow=False):
            problems.append(f'{other.name}: plugin bundle differs from the root bundle')
    for profile in ART_PROFILES:
        folder = home / 'profiles' / profile
        if not (folder / 'config.yaml').is_file():
            problems.append(f'profile {profile} is missing')
            continue
        text = (folder / 'config.yaml').read_text()
        provider, model = config_model(text)
        if provider not in ('anthropic', 'openai-codex', 'openrouter'):
            problems.append(f'profile {profile} uses provider {provider}')
        if '    - vision' not in text:
            problems.append(f'profile {profile} lacks the vision toolset')
        if 'dispatch_in_gateway: false' not in text:
            problems.append(f'profile {profile} must keep dispatch_in_gateway: false')
        if not (folder / 'plugins/factory-models').is_dir():
            problems.append(f'profile {profile} lacks the factory-models plugin')
        if not (folder / 'SOUL.md').read_text().strip():
            problems.append(f'profile {profile} has an empty SOUL.md')
    missing = set(ART_PROFILES) - set(roster((home / 'config.yaml').read_text()))
    if missing:
        problems.append(f'root kanban.dispatch_profiles lacks {sorted(missing)}')
    skills = home / 'factory-skills/worker'
    if not (skills / 'art-production/SKILL.md').is_file():
        problems.append('art-production skill is not installed')
    if '--fail-on-blocking' not in (skills / 'art-review/scripts/art_lint.py').read_text():
        problems.append('installed art_lint.py lacks --fail-on-blocking')
    print(json.dumps({'ok': not problems, 'problems': problems, 'cards': cards}, indent=2))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
```

Run: `chmod +x scripts/check_game_art_install.py`

- [ ] **Step 4: Run all of Part B**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_*.py' -v`
Expected: 33 tests OK

Run: `python3 scripts/check_game_art_install.py; echo rc=$?`
Expected (live install, before Part C): `"ok": false`, problems include `installed plugin bundle lacks the art type or profiles`, `art-director has no Factory default`, `an art task cannot be captured: Unsupported task type`, `profile artist is missing`, `art-production skill is not installed`; `rc=1`. This proves the checker is read-only and detects the current state.

- [ ] **Step 5: Export patches for review**

```sh
cd /Users/example/orca/projects/hermes
diff -ruN -x __pycache__ -x integrations ~/.hermes/factory-dashboard /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-dashboard > artifacts/game-art-2026-10-26/factory-dashboard.patch
diff -ruN -x __pycache__ -x tests ~/.hermes/scripts /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/scripts > artifacts/game-art-2026-10-26/scripts.patch
diff -ruN ~/.hermes/factory-skills/orchestrator/software-factory /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/factory-skills/orchestrator/software-factory > artifacts/game-art-2026-10-26/software-factory.patch
grep -c '^+++ ' artifacts/game-art-2026-10-26/*.patch
```

Expected (`diff` exits 1 when files differ): `factory-dashboard.patch:5`, `scripts.patch:4`, `software-factory.patch:1`. Show the three patches to the user before Part C.

---

# Part C: live rollout

Rules for every Part C task:
- **ASK THE USER FIRST** at each marked step and wait for an explicit yes.
- **Before every `hermes` command:** run the update check (Task 14 Step 1). If it shows an unfinished update or follow-up, or the command prints a "previous `hermes update`" warning, stop and ask the user. **After every `hermes` command:** run the gateway check (Task 14 Step 2) and confirm `running`.
- Profile models are `anthropic` or `openai-codex` (OpenRouter allowed); never `copilot`.
- No commits, pushes or PRs. No paid model or Tripo run outside Tasks 22-24.

### Task 14: Preflight (read-only)

- [ ] **Step 1: Update check**

```sh
tail -n 5 ~/.hermes/logs/update.log
ls -t ~/.hermes/logs/update_receipts | head -n 3
python3 -c "import json,pathlib; d=json.loads((pathlib.Path.home()/'.hermes/logs/update_receipts/latest.json').read_text()); print(d.get('kind'), d.get('outcome'), d.get('finished_at'))"
```

Expected: no line saying an update or follow-up "did not finish" newer than the last gateway start, and the latest receipt finished. As of 2026-10-26 the log ends with `Update follow-up 'gateway_restart' did not finish ...`: report this to the user and let them decide (for example run `hermes gateway restart` themselves) before any Part C `hermes` command.

- [ ] **Step 2: Gateway check (reused after every `hermes` call)**

```sh
python3 -c "import json,pathlib; d=json.loads((pathlib.Path.home()/'.hermes/gateway_state.json').read_text()); print(d['gateway_state'], d['pid'], d.get('active_agents'), d.get('updated_at'))"
```

Expected: `running <pid> 0 <recent time>`.

- [ ] **Step 3: No Factory work in flight**

```sh
python3 -c "import sqlite3,pathlib; c=sqlite3.connect('file:'+str(pathlib.Path.home()/'.hermes/kanban.db')+'?mode=ro',uri=True); print(c.execute(\"select status,count(*) from tasks where status not in ('done','archived') group by status\").fetchall())"
```

Expected: `[]`. If not empty, wait or ask the user.

- [ ] **Step 4: Record the dashboard command line**

```sh
pgrep -f serve_factory_dashboard.py
ps -o command= -p "$(pgrep -f serve_factory_dashboard.py)" | tee /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/dashboard-command.txt
lsof -a -p "$(pgrep -f serve_factory_dashboard.py)" -d cwd -Fn | tail -n 1
```

Expected: one PID; the command `.../venv/bin/python scripts/serve_factory_dashboard.py --policy-db ... --port 4610`; cwd `n/Users/example/.hermes/factory-dashboard`.

- [ ] **Step 5: Live baseline still matches the copy's baseline**

Run: `cd ~/.hermes && shasum -a 256 -c /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/baseline.sha256`
Expected: 10 lines ending `: OK`. If any line fails, stop: the live file changed after Task 8; redo Part B against it.

---

### Task 15: Pause new claims and back up (ASK THE USER FIRST)

- [ ] **Step 1: Pause (ASK THE USER FIRST; run Task 14 Step 1 first)**

Run: `hermes pause --reason "game art rollout"`
Expected: `Hermes paused` and `sentinel: /Users/example/.hermes/ESTOP`. Then Task 14 Step 2: still `running`.

Run: `ls -l ~/.hermes/ESTOP`
Expected: the file exists. Remember that this rollout created the pause (Task 20 releases it).

- [ ] **Step 2: Back up (ASK THE USER FIRST; writes only under ~/.hermes/backups)**

```sh
B=~/.hermes/backups/game-art-$(date +%Y%m%d-%H%M%S)
mkdir -m 700 -p "$B/db" && echo "$B" | tee /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/backup-path.txt
cd ~/.hermes && tar czf "$B/files.tgz" --exclude __pycache__ \
  factory-dashboard plugins/factory-models scripts config.yaml \
  factory-skills/worker/art-review factory-skills/orchestrator/software-factory \
  state/factory/model-catalog.json state/factory/repos.json state/factory/config.json \
  profiles/*/plugins/factory-models profiles/*/config.yaml profiles/*/SOUL.md
for db in state/factory/task-settings.db kanban.db state/factory/dashboard-policy.db; do
  sqlite3 "$HOME/.hermes/$db" ".backup '$B/db/$(basename "$db")'"
done
sqlite3 "$B/db/task-settings.db" 'pragma integrity_check; select revision from factory_defaults;'
tar tzf "$B/files.tgz" | grep -c 'plugins/factory-models/factory_dashboard/workflow_types.py'
```

Expected: `ok`, `1` (defaults revision), and `14` (root plugin + 13 profile homes).

---

### Task 16: Install the source edits and the skills (ASK THE USER FIRST)

- [ ] **Step 1: Copy the edited files from the copy (ASK THE USER FIRST)**

```sh
cd /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build
for f in factory-dashboard/factory_dashboard/workflow_types.py factory-dashboard/factory_dashboard/workflow_templates.py \
         factory-dashboard/factory_dashboard/task_submission.py factory-dashboard/factory_dashboard/assets/workflow_forms.js \
         factory-dashboard/factory_dashboard/assets/task_forms.js scripts/factory_lib.py scripts/factory_ticket.py \
         scripts/factory_intake.py scripts/factory_publish.py factory-skills/orchestrator/software-factory/SKILL.md; do
  cp "$f" "$HOME/.hermes/$f"
done
cd ~/.hermes && for f in factory-dashboard/factory_dashboard/*.py scripts/factory_*.py; do cmp -s "$f" "/Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/build/$f" || echo "DIFF $f"; done
```

Expected: no `DIFF` lines.

- [ ] **Step 2: Reinstall art-review (adds `--fail-on-blocking` / `--check-bible`) and install art-production (ASK THE USER FIRST)**

```sh
B=$(cat /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/backup-path.txt)
mv ~/.hermes/factory-skills/worker/art-review "$B/art-review.previous"
cd /Users/example/orca/projects/hermes
sh scripts/install_art_review.sh
sh scripts/install_art_production.sh
python3 ~/.hermes/factory-skills/worker/art-review/scripts/art_lint.py /tmp --check-bible; echo rc=$?
```

Expected: `installed .../art-review`, `installed .../art-production`, then `{"bible": "invalid", ...}` and `rc=1`.

---

### Task 17: Run the migration on the live store (ASK THE USER FIRST)

- [ ] **Step 1: Dry run**

```sh
cd /Users/example/orca/projects/hermes
python3 scripts/migrate_game_art.py --dashboard-source ~/.hermes/factory-dashboard \
  --settings-db ~/.hermes/state/factory/task-settings.db --catalog ~/.hermes/state/factory/model-catalog.json --dry-run
```

Expected: `{"catalog_add": ["art-director", "art-reviewer", "artist"], "defaults_revision": 1, "roles_add": ["art-director", "art-reviewer", "artist"], "template": null, "type_default": null}`

- [ ] **Step 2: Stop the dashboard before applying (ASK THE USER FIRST)**

The running dashboard process loaded the pre-art code; it must never serve or write the migrated store. Stop it now; Task 20 Step 2 starts it on the new code (if the rollout is abandoned after Step 3, start it again at once with the same command).

```sh
kill "$(pgrep -f serve_factory_dashboard.py)"; sleep 2; pgrep -f serve_factory_dashboard.py || echo stopped
```

Expected: `stopped` (`dashboard-command.txt` from Task 14 holds the start command).

- [ ] **Step 3: Apply (ASK THE USER FIRST)**

Note (M1): apply is not one atomic transaction: catalog, role defaults, template and type default are four separate steps. Each step is idempotent and skips what is already there, so after an interruption or a failed step, fix the cause and run Step 3 again (with a new `--receipt` path); re-runs converge on the same final state.

```sh
B=$(cat artifacts/game-art-2026-10-26/backup-path.txt)
python3 scripts/migrate_game_art.py --dashboard-source ~/.hermes/factory-dashboard \
  --settings-db ~/.hermes/state/factory/task-settings.db --catalog ~/.hermes/state/factory/model-catalog.json \
  --apply --receipt "$B/migration-apply.json"
```

Expected: JSON with `catalog_added` and `roles_added` listing the three roles, `defaults_revision: 2`, and the same UUID in `template_created` and `type_default_set`. Running Step 1 again shows empty lists and that UUID as `template` and `type_default`.

---

### Task 18: Rebundle the plugin and swap it in every home (ASK THE USER FIRST)

- [ ] **Step 1: Build a fresh bundle from the installed source**

```sh
B=$(cat /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/backup-path.txt)
mkdir -p ~/.hermes/factory-dashboard/integrations/hermes_factory_models
cp ~/.hermes/plugins/factory-models/plugin.yaml ~/.hermes/plugins/factory-models/__init__.py ~/.hermes/factory-dashboard/integrations/hermes_factory_models/
python3 ~/.hermes/factory-dashboard/scripts/bundle_factory_plugin.py "$B/plugin-new/factory-models"
grep -c "'art'" "$B/plugin-new/factory-models/factory_dashboard/workflow_types.py"
```

Expected: the bundle path, then `1`.

- [ ] **Step 2: Swap in the root home and every profile home (ASK THE USER FIRST)**

Old copies go to the backup, never next to the new one (two `factory-models` plugin folders would both be discovered).

```sh
B=$(cat /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/backup-path.txt)
mkdir -p "$B/plugin-old"
for home in ~/.hermes ~/.hermes/profiles/*; do
  [ -d "$home/plugins/factory-models" ] || continue
  name=$(basename "$home")
  mv "$home/plugins/factory-models" "$B/plugin-old/$name"
  cp -R "$B/plugin-new/factory-models" "$home/plugins/factory-models"
done
for home in ~/.hermes ~/.hermes/profiles/*; do
  [ -d "$home/plugins/factory-models" ] && diff -rq -x __pycache__ "$B/plugin-new/factory-models" "$home/plugins/factory-models"
done; echo done
```

Expected: only `done` (no diff lines); `ls "$B/plugin-old" | wc -l` prints `14`.

---

### Task 19: Profiles and roster (ASK THE USER FIRST)

- [ ] **Step 1: Create the two profiles (ASK THE USER FIRST; Task 14 Step 1 before, Step 2 after each command)**

```sh
hermes profile create art-director --clone-from architect --no-alias --description "Factory art director: plans game art (prepare stage)"
hermes profile create artist --clone-from developer --no-alias --description "Factory artist: makes game art (implement and repair stages)"
```

Expected: each prints that the profile was created; `ls ~/.hermes/profiles/art-director/config.yaml ~/.hermes/profiles/artist/config.yaml` lists both.

Check the models (cloned from architect and developer, already the spec's values):

Run: `head -3 ~/.hermes/profiles/art-director/config.yaml ~/.hermes/profiles/artist/config.yaml`
Expected: `provider: anthropic` / `default: claude-opus-5-5` and `provider: openai-codex` / `default: gpt-6-luna`. If either differs, edit those two lines to these values; never `copilot`.

Check what was carried over:

Run: `grep -c 'dispatch_in_gateway: false\|factory-models\|hermes_otel' ~/.hermes/profiles/art-director/config.yaml ~/.hermes/profiles/artist/config.yaml; grep -c 'workspace-write-guard.py --writer' ~/.hermes/profiles/artist/config.yaml; grep -c '^terminal:' ~/.hermes/profiles/artist/config.yaml`
Expected: at least 3 for each file (plugins, plugin entry, kanban guard); `1` writer hook for the artist; `0` top-level `terminal:` sections.

- [ ] **Step 2: Toolsets, Tripo key passthrough, souls and plugin (ASK THE USER FIRST)**

In `~/.hermes/profiles/art-director/config.yaml` and `~/.hermes/profiles/artist/config.yaml` (Edit tool, exact strings) replace:

```yaml
    - terminal
kanban:
```

with:

```yaml
    - terminal
    - vision
kanban:
```

Append to the end of `~/.hermes/profiles/artist/config.yaml`:

```yaml
terminal:
  # Tripo key for art-production's tripo_model.py (non-provider secrets reach terminals only when listed).
  env_passthrough:
    - TRIPO_API_KEY
```

Then:

```sh
S=~/.hermes/factory-skills/worker/art-production/souls
cp "$S/art-director.SOUL.md" ~/.hermes/profiles/art-director/SOUL.md
cp "$S/artist.SOUL.md" ~/.hermes/profiles/artist/SOUL.md
B=$(cat /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/backup-path.txt)
for p in art-director artist; do
  [ -d ~/.hermes/profiles/$p/plugins/factory-models ] || { mkdir -p ~/.hermes/profiles/$p/plugins && cp -R "$B/plugin-new/factory-models" ~/.hermes/profiles/$p/plugins/factory-models; }
done
ls ~/.hermes/profiles/art-director/auth.json ~/.hermes/profiles/artist/auth.json
```

Expected: both `auth.json` files listed (the clone copies credentials). Ask the user to add `TRIPO_API_KEY=...` to `~/.hermes/profiles/artist/.env` themselves; never read or print that file.

- [ ] **Step 3: Root roster (ASK THE USER FIRST)**

In `~/.hermes/config.yaml` (Edit tool) replace:

```yaml
    - ui-reviewer
    - fixer
code_execution:
```

with:

```yaml
    - ui-reviewer
    - fixer
    - art-director
    - artist
    - art-reviewer
code_execution:
```

The per-profile `dispatch_profiles` lists are guards for manual `hermes -p <profile> kanban dispatch`; they stay as cloned.

---

### Task 20: Restart gateway and dashboard, release the pause (ASK THE USER FIRST)

- [ ] **Step 1: Gateway (ASK THE USER FIRST; Task 14 Step 1 first)**

Run: `hermes gateway restart`
Then Task 14 Step 2. Expected: `running` with a **new** PID and a fresh `updated_at`.

- [ ] **Step 2: Start the dashboard on the new code (ASK THE USER FIRST)**

It has been stopped since Task 17 Step 2, so the old code never ran against the migrated store.

```sh
pgrep -f serve_factory_dashboard.py && echo "ALREADY RUNNING: stop it first"
cd ~/.hermes/factory-dashboard && nohup $(cat /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/dashboard-command.txt) >> ~/.hermes/logs/factory-dashboard.log 2>&1 &
curl -s http://127.0.0.1:4610/api/workflows | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['enabled'], d['readiness'].get('ready'), d['defaults']['templates'].get('art') is not None, d['capabilities']['artist'])"
```

Expected (allow a few seconds for start-up): `True True True ['implement', 'repair']`.

- [ ] **Step 3: Release the pause this rollout created (ASK THE USER FIRST)**

Only after Task 21 Step 1 passes. Task 14 Step 1 first, then `hermes resume`, then Task 14 Step 2.
Expected: `Hermes resumed`; `ls ~/.hermes/ESTOP` → `No such file or directory`.

---

### Task 21: Verify without launching workers

A disposable kanban board does not exercise this: managed workflows run only on the configured default board (`factory_intake.py`: "Managed workflow execution is registered only on the configured default Factory board"). The checker captures an Art task on a private copy of the live settings store with the installed plugin code and builds every stage card.

- [ ] **Step 1: Run the install checker (read-only)**

Run: `cd /Users/example/orca/projects/hermes && python3 scripts/check_game_art_install.py`
Expected: `"ok": true`, `"problems": []`, and cards `prepare: art-director/scratch`, `implement: artist/dir`, `repair: artist/dir`, `art-reviewer: art-reviewer/scratch`, `claude-reviewer: claude-reviewer/scratch`, `verify: verifier/scratch`, each with `skills: ["factory-worker"]`.

- [ ] **Step 2: Dashboard forms**

Open http://127.0.0.1:4610, **Workflows**: Game Art is listed as the `art` default with art-director / artist / art-reviewer + claude-reviewer / verifier / artist, repairs 2. **New task**: Type offers `art`; choosing it previews Game Art. Do not submit.

- [ ] **Step 3: Step 2 of the spec (art-reviewer in any template)**

In **Workflows**, open Feature, tick `art-reviewer` in the review panel and check the preview validates; **Cancel** without saving (saving would make a new Feature revision the user did not ask for).

---

### Task 22: Tool checks with real services (ASK THE USER FIRST; small spend)

- [ ] **Step 1: One real Codex image (uses the user's Codex plan)**

```sh
mkdir -p /tmp/game-art-check
printf 'Use case: stylized-concept\nAsset type: game item sprite concept\nPrimary request: a small red health potion in a round glass bottle with a cork\nStyle/medium: clean pixel-art friendly illustration\nComposition/framing: one centred object on a flat plain white background\nConstraints: no text, no shadow, no frame\n' > /tmp/game-art-check/potion.txt
time sh ~/.hermes/factory-skills/worker/art-production/scripts/codex_image.sh /tmp/game-art-check/potion.txt /tmp/game-art-check/potion.png
python3 ~/.hermes/factory-skills/worker/art-production/scripts/sprite_fit.py /tmp/game-art-check/potion.png /tmp/game-art-check/potion-32.png --size 32x32
```

Expected: `{"width": ..., "height": ...}` within 300 s, then a 32x32 sprite. Open both images. If the first command fails, keep the log line it prints and fix `codex_image.sh` (flags or copy step) before Task 23.

- [ ] **Step 2: Tripo key and balance (free)**

After the user has put the key in the artist `.env`:

```sh
( set -a; . ~/.hermes/profiles/artist/.env; set +a; python3 ~/.hermes/factory-skills/worker/art-production/scripts/tripo_model.py --balance )
```

Expected: `{"balance": {"balance": <number>, "frozen": <number>}}`. Exit 3 with "rejected the API key" means a wrong key or region. The key is never printed.

---

### Task 23: Paid end-to-end asset task (ASK THE USER FIRST)

- [ ] **Step 1: Sample game and registration (ASK THE USER FIRST)**

Run: `python3 scripts/make_art_sample.py ~/factory-samples/art-sample`
Expected: the absolute folder path. It is a plain folder (no Git), so intake uses `ISOLATION: dir` and the artist writes into it directly.

Add to `~/.hermes/state/factory/repos.json` under `"repos"` (Edit tool):

```json
  "art-sample": {
   "path": "/Users/example/factory-samples/art-sample",
   "auto_pr": false
  },
```

- [ ] **Step 2: Submit (ASK THE USER FIRST; paid: art-director, artist, reviewers, verifier, one Tripo task)**

Dashboard **New task**: title `Potion sprite and crate prop`, project `art-sample`, type `art`, prompt `Make a 32x32 health potion item sprite at Assets/Art/Items/potion.png and a low-poly wooden crate prop at Assets/Models/Props/crate.glb, following the style bible.`, acceptance empty. Submit once.

- [ ] **Step 3: Watch and record**

Expected sequence on the timeline: PLAN (art-director) → IMPLEMENT (artist) → ART-REVIEWER + CLAUDE-REVIEWER + VERIFY → delivered (or a repair cycle, at most 2). Record for the results doc: the PLAN's ACs, the artist's `assets`, `fallbacks` and `tripo_tasks` metadata, the verifier's art lint check result, total time, and both files in `~/factory-samples/art-sample`. Then run `python3 ~/.hermes/factory-skills/worker/art-review/scripts/art_lint.py ~/factory-samples/art-sample --out /tmp/game-art-check/final-lint --fail-on-blocking; echo rc=$?` → `rc=0`.

---

### Task 24: Paid style task (ASK THE USER FIRST)

- [ ] **Step 1: Empty folder, registration and submission (ASK THE USER FIRST)**

Run: `mkdir -p ~/factory-samples/style-sample && printf '# Style sample\n' > ~/factory-samples/style-sample/README.md`

Register `"style-sample"` in `repos.json` like Task 23. Submit an art task: title `Style bible for a cosy farming game`, project `style-sample`, prompt `Create the style bible for a cosy top-down farming game: 32x32 pixel-art sprites and low-poly props.`

Expected: PLAN says `Kind: style`; the artist writes `art/style/` (STYLE.md, style.json, palette, 2-3 references); the verifier's ACs include `--check-bible` printing `"bible": "ok"`. Accepting the delivered folder is the user's approval of the bible.

- [ ] **Step 2: Blocked-without-bible check (optional, ASK; one art-director run)**

Submit an asset task (`Make a 32x32 carrot item sprite`) to a third empty registered folder. Expected: the root stops at preparation as **blocked** with reason `no approved style bible: submit an Art task asking for a style bible`; no IMPLEMENT card is created.

---

### Task 25: Results and rollback documentation

- [ ] **Step 1: Write `docs/game-art-factory-results.md`**

Sections: Validation (Part A and Part B test counts, checker output), Deployment evidence (backup path, migration receipt, gateway and dashboard PIDs, plugin homes swapped), Paid runs (Tasks 22-24 records, Tripo task IDs and balance before/after), Decisions (copy the "Decisions grounded in the installed code" list), Rollback (below). No secrets.

- [ ] **Step 2: Rollback procedure (include verbatim in the results doc)**

1. Task 14 Step 1, then `hermes pause --reason "game art rollback"`.
2. `python3 scripts/migrate_game_art.py --dashboard-source ~/.hermes/factory-dashboard --settings-db ~/.hermes/state/factory/task-settings.db --catalog ~/.hermes/state/factory/model-catalog.json --rollback --receipt "$B/migration-rollback.json"`. This removes the `art` type default and archives Game Art. Role rows and catalog entries stay unused. Existing tasks keep their frozen snapshots and keep running on the installed (new) code.
3. Remove `art-director`, `artist`, `art-reviewer` from the root `kanban.dispatch_profiles` if the profiles must not be scheduled.
4. Restoring the old source, plugin and config from `$B/files.tgz` is allowed only after `--rollback --purge-template` succeeds (it refuses once any art task was captured or another template uses an art profile). Otherwise keep the new source: it is additive.
5. `hermes gateway restart`, restart the dashboard as in Task 20 Step 2, Task 14 Step 2, then `hermes resume`.

Never overwrite the live sqlite stores with the backup copies after new tasks exist.

---

## Self-review against the spec

**Coverage**

| Spec item | Where |
|---|---|
| `art` task type, every enumeration | Tasks 9 (`TASK_TYPES`), 10 (`task_submission.py`, both JS forms, orchestrator skill), 11 (`factory_lib`, `factory_ticket`, `factory_intake`, `factory_publish`) |
| Capability map, art-reviewer `review` anywhere (step 2) | Task 9; Task 21 Step 3 |
| Game Art preset and type default via migration | Tasks 9, 12, 17 |
| Reviewer rule kept, Game Art includes claude-reviewer | Task 9 `test_a_code_reviewer_is_still_required` |
| Writer/reviewer independence | Task 9 `test_writers_and_readers_stay_independent` |
| Role rows + revision bump, catalog entries, roster | Tasks 12, 17, 19 |
| Art Director plan contract (bible check, asset list, ACs, include list, style task) | Task 6 soul, Task 9 prepare instructions, Task 1 `--check-bible` |
| Artist tools: `codex_image.sh`, `tripo_model.py`, `blender_model.py` (cleanup, blockout) via `blender_run.sh`, `sprite_fit.py` | Tasks 2-5 |
| Exit 3 fallback, no retry of charged tasks, 5 s / 10 min polling | Task 3 tests |
| Completion metadata `assets`, `fallbacks`, `tripo_tasks`; repair scope; no `art/style/` in asset tasks | Task 6 skill and soul; Task 9 implement/repair instructions |
| Lint gate (`--fail-on-blocking`) | Task 1; verify instructions (Task 9) |
| Profiles (models, toolsets, skills, cloned floor, `dispatch_in_gateway: false`) | Task 19; checked by Task 21 |
| Backup, pause, build in copy, rebundle, restart, disposable verification, paid runs, rollback | Tasks 8, 14-25 |
| Validation list (unit tests, fake HTTP Tripo, Blender test on the cube fixture, stub codex) | Tasks 2-5, 9-13 |

**Placeholders:** every code step contains the full file or the exact old/new strings. Part C commands use the recorded backup path file rather than a placeholder.

**Name consistency:** profiles `art-director`, `artist`, `art-reviewer`; skill `art-production`; template `Game Art`; type `art`; scripts `codex_image.sh`, `tripo_model.py`, `blender_run.sh`, `blender_model.py`, `sprite_fit.py`, `check_png.py`, `migrate_game_art.py`, `check_game_art_install.py`; flags `--fail-on-blocking`, `--check-bible`, `--purge-template`. The tests assert these exact names.

**Deviations from the spec (all forced by the installed code; see Decisions):** GATE via verify instructions instead of a plan GATE line; added `--check-bible`; prep BLOCKED gives phase `blocked`; branch `art/` and title `feat(art):` instead of an `ART` prefix; rollback keeps the new source unless the template can be purged; plugin swapped in all 14 homes; dashboard stopped before the live migration (Task 17 Step 2) and started on the new code in Task 20.
