# Hermes Factory Toolkit

Tools and extensions for Hermes Factory workflows: game art and audio production, asset review, workflow migrations, and offline evaluation.

This checkout complements an existing Hermes Factory installation. It is not a standalone Hermes server or dashboard application. Asset linting, sound synthesis, and benchmark tooling can run directly from the checkout; workflow migrations and installed worker skills require the corresponding Factory runtime.

## Agents and workflow

Factory v2 plans the project first: the art/audio directors plan when needed, a human approves the art plan, and the architect splits the work into small dependent tasks. Each task then runs its own cycle of writing, verification, reviews, and bounded specialist repairs; a task that cannot be repaired goes back to the architect for a replan.

<p align="center">
  <img src="docs/images/factory-agents.svg" alt="Factory v2: relevant directors before architecture, small dependent tasks, verification before reviews, specialist repairs with scoped re-reviews, bounded replanning, final integration, factory-retro, and the human touchpoints: request, art plan approval, review and recovery." width="100%">
</p>

Final integration repeats the cycle over the assembled project with the complete review panel, and `factory-retro` then proposes improvements to Factory itself. Existing tasks retain their captured v1 workflows.

See the [project workflow guide](docs/project-workflows.md) for the execution contract, installation, and verification. The runtime source in [`runtime/factory-dashboard`](runtime/factory-dashboard) is installed into an existing Hermes home rather than run from this checkout.

## Requirements

- **Python 3.11+** for the Python tools. The core lint, synthesis, and benchmark code uses only the standard library.
- **FFmpeg** for decoding and processing audio and measuring loudness.
- **Blender** for rendering and inspecting 3D assets.
- **A POSIX shell and `rsync`** for the installer scripts.
- **Hermes Factory and configured worker profiles** for model-backed reviews and managed workflows. Production wrappers may also require their respective generation service credentials or CLI.
- **PyYAML in the Hermes Python environment** for the project workflow installer.

Run the commands below from the repository root. Individual scripts expose their arguments through `--help`.

## Quick start

### Validate the benchmark taskset

This runs offline without a Hermes installation or model calls:

```sh
python3 scripts/factory_benchmark.py taskset --taskset benchmarks/factory-v1
```

Generate a report from the included synthetic example:

```sh
python3 scripts/factory_benchmark.py report \
  --taskset benchmarks/factory-v1 \
  --results benchmarks/factory-v1/examples/results.json \
  --evidence-root benchmarks/factory-v1/examples \
  --output /tmp/factory-benchmark-example
```

The command writes `/tmp/factory-benchmark-example.json` and `/tmp/factory-benchmark-example.md`. These sample results demonstrate report mechanics; they are not measured model performance. See the [benchmark guide](docs/factory-ecc.md) for preparing cases, collecting evidence, and running real trials.

### Lint game assets

Art lint uses the target project's `art/style/STYLE.md` and `art/style/style.json`:

```sh
python3 scripts/art_lint.py /path/to/game --out /tmp/art-lint
```

Audio lint uses `audio/style/AUDIO.md` and `audio/style/audio.json`:

```sh
python3 scripts/audio_lint.py /path/to/game --out /tmp/audio-lint
```

Both commands produce `lint.json` and review images in the output directory. Pass relative asset paths after the game directory to limit the review. Audio lint also supports `--fail-on-blocking` for a nonzero exit on BLOCKER or HIGH findings.

Art checks inspect assets outside the game engine. Model-backed art review is a separate step; see the [art verifier guide](docs/art-verifier.md).

### Produce audio

Render a sound-effect recipe to a WAV file:

```sh
python3 scripts/sfx_synth.py /path/to/recipe.json /tmp/effect.wav
```

Process an existing music file using a music class defined in the game's audio bible:

```sh
python3 scripts/music_process.py /path/to/incoming.mp3 /tmp/track.ogg \
  --class YOUR_MUSIC_CLASS \
  --bible /path/to/game/audio/style/audio.json
```

The [audio production instructions](audio_production/install/SKILL.md) describe recipe fields, music cues, and import conventions. Music generation itself is handled outside this tool: the processing command consumes a supplied audio file.

## Install worker skills

Install the review and production bundles:

```sh
sh scripts/install_art_review.sh
sh scripts/install_art_production.sh
sh scripts/install_audio_review.sh
sh scripts/install_audio_production.sh
```

The default destination is `~/.hermes/factory-skills/worker`. Set `HERMES_FACTORY_SKILLS` to use another worker-skill directory. Installers refuse to overwrite an existing destination.

The architect's `task-writing` skill (how to write small, checkable tasks) is a runtime skill, kept in [`runtime/factory-skills/worker/task-writing`](runtime/factory-skills/worker/task-writing); copy that folder into the same destination.

Installing skill files does not configure worker profiles or activate workflow types. Review the [art](docs/superpowers/specs/2026-10-26-game-art-factory-design.md) and [audio](docs/superpowers/specs/2026-11-06-game-audio-factory-design.md) integration designs before changing an installed environment. Migration scripts accept explicit runtime paths and provide preview modes:

```sh
python3 scripts/migrate_game_art.py --help
python3 scripts/migrate_game_audio.py --help
python3 scripts/migrate_factory_ecc.py --help
```

The Game Art and Game Audio migrations use `--dry-run`; the ECC migration creates a preview that must be supplied when applying changes. See the [ECC guide](docs/factory-ecc.md) for its activation and rollback procedure.

## Repository layout

```text
art_production/           Art generation and sprite fitting helpers
audio_production/         Sound synthesis and music processing
factory_art/             Art linting, style rules, and model checks
factory_audio/           Audio linting, measurements, and FFmpeg integration
factory_ecc/             Benchmark evidence, reporting, and guidance migration
factory_game_art/        Game Art workflow migration
factory_game_audio/      Game Audio workflow migration
factory_type_migration/  Shared workflow type migration support
scripts/                 Command-line entry points and installers
tests/                   unittest suites grouped by subsystem
benchmarks/              Pinned cases, graders, and synthetic examples
docs/                    Guides, designs, implementation plans, and results
runtime/                 Factory dashboard runtime and worker skills installed into Hermes
reports/                 Retained HTML dashboard snapshots
artifacts/               Archived builds and rollout evidence
```

## Verification

Run a subsystem's tests with Python's built-in test runner:

```sh
python3 -m unittest discover -s tests/ecc -p 'test_*.py' -v
python3 -m unittest discover -s tests/art -p 'test_*.py' -v
python3 -m unittest discover -s tests/audio -p 'test_*.py' -v
```

Additional suites are in `tests/production`, `tests/factory_art_type`, `tests/factory_audio_type`, `tests/factory_worker` (the manifest helper) and `tests/hermes_patches` (the Hermes patch tool); run them with the same discovery command and the corresponding directory. Some checks depend on external tools or an installed runtime. The live grader check described in the benchmark guide additionally requires Docker and the Factory runtime image.

## Further reading

- [Workflow templates and captured task settings](docs/factory-workflows.md)
- [Factory dashboard snapshots](docs/factory-dashboard.md)
- [Timeline controls](docs/factory-timeline-controls.md)
- [PR writer behavior](docs/factory-pr-writer.md)

Some operational guides reference scripts in the owning Hermes home or a separate dashboard worktree. Retained artifacts and reports record particular rollouts rather than the current state of a running Factory.
