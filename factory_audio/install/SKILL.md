---
name: audio-review
description: Procedure and scripts for the audio-reviewer - measure sound effects and music against a repo's audio/style bible, then judge each asset against its recipe or cue and the AUDIO.md rules.
---

# Audio review

`LINT` means `python3 ${HERMES_SKILL_DIR}/scripts/audio_lint.py`. Run it as its own terminal command, never through `bash -c` or a pipe.

## 1. Lint

`LINT <src_dir> --out <workspace>/lint`

It prints a one-line JSON summary. Full results are in `<workspace>/lint/lint.json`:
- `audio_files`: 0 means there is nothing to review. Complete `NO_BLOCKING_FINDINGS` with `audio_surface: "none"`.
- `findings` and `lines`: measured facts. Never drop, downgrade or dispute them.
- `assets[]`: `file`, `class`, `kind`, `rules`, `measures` (duration, sample rate, channels, peak_dbfs, lufs, edge silence, loop_seam), `images` (waveform and spectrum PNGs).
- Edge silence is checked against the class `silence_max_ms` (0 means no silence allowed; a class without it is not checked). Measures that are not finite (a silent file's peak or loudness) are `null`.
- Files longer than 600 s are not decoded; they get a HIGH `duration` finding.
- `unverified`: ffmpeg missing or failing is an environment problem, not the asset's fault.

## 2. Judge

You cannot listen. Judge from the measures, the recipe or cue, and the pictures.

Read `<src_dir>/audio/style/AUDIO.md`, then for each asset:
- **SFX:** read its recipe in `audio/recipes/<name>.json`. Check that the recipe matches what the PLAN describes (for example, a "jump" should rise in pitch: `freq_end > freq_start`; a "UI click" should be short with a fast decay) and the asset's AUDIO.md rules. Open the waveform picture with `vision_analyze` when the envelope matters.
- **Music:** read its cue in `audio/cues/<name>.md`. Check that the duration, loop flag and BPM are consistent with the cue, and that the measures meet the class.

Each finding names the rule ID (or the PLAN/recipe line) it breaks. A finding is at most MEDIUM unless AUDIO.md marks the cited rule `(blocking)`. Something that breaks no listed rule is a NIT `style gap: <suggested rule>`.

## 3. Report

In factory mode, follow the factory-worker review contract. Findings are `F<n>|SEV|<AC or ->|<file>|[<rule>] <problem>`. Lint findings are copied as they are, with the check name as the rule.
