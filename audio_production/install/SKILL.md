---
name: audio-production
description: Procedure and scripts for the Factory sound-designer - sfxr-style sound effect synthesis from JSON recipes, Suno music cue sheets, and processing user-supplied Suno files into game-ready OGG.
---

# Audio production

Tools. Run each as its own terminal command:
- `SYNTH` = `python3 ${HERMES_SKILL_DIR}/scripts/sfx_synth.py <recipe.json> <out.wav>`. Exit 2 means a bad recipe; the message names the key.
- `MUSIC` = `python3 ${HERMES_SKILL_DIR}/scripts/music_process.py <incoming file> <out> --class <music class> --bible <PROJECT_DIR>/audio/style/audio.json [--loop] [--bpm N] [--loop-end S]`. Exit 1 means processing failed; read stderr.
- `LINT` = `python3 ${AUDIO_REVIEW_DIR}/scripts/audio_lint.py <PROJECT_DIR> <changed audio paths> --out <PROJECT_DIR>/.factory/tmp/audio-lint --fail-on-blocking`. Exit 1 means a BLOCKER or HIGH finding; read `lint.json` there.

Scratch output goes under `PROJECT_DIR/.factory/tmp/`. Deliverables go only to the paths in PLAN.md.

## Before you start

Read `.factory/PLAN.md`, `audio/style/AUDIO.md` and `audio/style/audio.json`. For each asset, note its class: format, rate, channels, duration range, loudness, peak and loop.

## Recipe keys (SFX)

- `wave`: square, saw, sine, triangle or noise.
- `freq_start` and `freq_end`: Hz, sliding from start to end.
- `attack`, `sustain`, `decay`: seconds.
- `sustain_punch`: 0–1.
- `vibrato_depth` (semitones) and `vibrato_hz`.
- `arp_semitones` and `arp_at`: 0–1.
- `duty`: square duty.
- `lowpass_hz` and `highpass_hz`.
- `volume`: 0–1.
- `seed`.
- `sample_rate` and `channels`: set these from the class.
- `peak_dbfs_max`: set from the class.

Common shapes:
- **Jump:** square, rising slide.
- **Coin:** square with a +7 semitone arp at about 0.3.
- **Hit:** noise with a fast decay and low-pass.
- **Laser:** saw with a falling slide.
- **UI click:** sine or triangle, under 80 ms, high-pass.

## SFX task

1. Write `audio/recipes/<name>.json` for each effect.
2. Run `SYNTH` to its target path.
3. Run `LINT` on the targets. If it reports a finding, change only that recipe (volume, length, filters) and re-render, up to twice per asset.

## Music cues task

For each cue, write `audio/cues/<name>.md` with these lines:
- `target: <class path>.ogg`
- `class: <music class>`
- `loop: true|false`
- `bpm: <n>`
- `length: <seconds>`

Then add a section `## Suno prompt` containing:
- the style tags, under 200 characters;
- `Instrumental` or the lyrics;
- a one-line description.

Then add `## Save as` naming `audio/incoming/<name>.mp3` (or .wav).

Write no audio. Your completion summary lists every cue and the incoming file name the user must save.

## Music import task

For each cue with a file in `audio/incoming/`, run `MUSIC` to the cue's `target`, using `--loop` and `--bpm` from the cue. Run `LINT` on the targets. List cues without an incoming file under `missing` in the metadata. Never edit or delete anything in `audio/incoming/`.

## Completion

Metadata:
- `assets`: a list of `{path, kind: sfx|music, route: synth|suno, recipe|cue}`.
- `missing`: a list.
- `checks_run`: includes the LINT command.

## Rules

- Never write `audio/style/` except in a style task.
- Never write `audio/incoming/`.
- Never call a paid audio service.
