# Art verifier validation results (26 October 2026)

## Tests

`python3 -m unittest discover -s tests/art -p 'test_*.py'`: 61 tests OK, none skipped. This includes the real Blender 4.1 render test.

## Review and fixes

An independent review found one critical issue, three important issues and seven minor ones. All were reproduced with probes. The following were fixed, each with a regression test that failed first:

- Stale Blender stats were reused after a crash (critical).
- Malformed PNGs crashed lint.
- `art_check.sh` followed symlinks out of the repo.
- Review-image folder names could collide.
- Non-UTF-8 bible files crashed lint.
- Float and boolean palette tolerances were accepted.
- Reference images did not count toward the 40-image budget.
- The installed skill used an ambiguous `${HERMES_SKILL_DIR}` lint path.
- Blender's internal "Viewer Node" image was counted as a model texture (found during Task 8).

Left as is: a broken bible in a repo whose only art is JSON text is not flagged. The sample game is generated at test time instead of stored as files.

## Install

- A backup was taken first: `~/.hermes/backups/pre-art-reviewer-<timestamp>.tgz` (ui-reviewer profile and factory-skills).
- The skill is installed at `~/.hermes/factory-skills/worker/art-review`.
- The `art-reviewer` profile was cloned from ui-reviewer, with `hermes_otel` and `factory-models` plugins as on other profiles and `dispatch_in_gateway: false`.
- The profile is not in the root dispatch roster or any workflow template.
- The model is `anthropic` / `claude-sonnet-5-5`. The Copilot/Gemini setting copied from ui-reviewer returned HTTP 403 "not licensed to use Copilot". The previous config is kept as `config.yaml.pre-model`, and the Copilot `auth.json` is moved aside as `auth.json.copilot-unused`.

Incident: the first `hermes chat` call completed a pending Hermes update (v0.21.7 → v0.22.2) and stopped the gateway. The gateway was restarted with the user's approval. launchd cannot load it on this macOS (`launchctl` exit 5), so it runs as a detached process without auto-start or auto-restart. Other Copilot-backed factory profiles are likely affected by the same 403.

## Manual review run

Command: `ART_CHECK_OUT=/private/tmp/art-review-run art_check.sh /private/tmp/art-testgame`. The report is at `/private/tmp/art-review-run/report.md`.

- **Lint findings:** all 11 expected findings appear unchanged, and the agent did not drop or downgrade any of them.
- **Crate model:** Blender rendered it, and lint wrote a contact sheet. There are no model findings and nothing is marked unverified.
- **Images:** 17 images were prepared, and the agent reports opening 14 of them with `vision_analyze`. Nothing was over the image budget.
- **Vision and text findings:** there were 2.
  - F13 is HIGH on S1, a `(blocking)` rule. The opaque sprite has no silhouette, and the finding cites three view paths plus the reference image.
  - F12 is LOW on T1, for urgent wording.
  - Both cite rule IDs. No finding on a non-blocking rule went above MEDIUM.
- **Style gaps:** observations outside the rules were reported as NIT style-gap suggestions, such as "S2 cannot be judged without a shaded reference".
- **Verdict:** `CHANGES_REQUIRED`, as expected.

## Not run

No real Codex-generated sprite has been tested yet, because none was provided. Factory (kanban) mode was not exercised; the profile is intentionally not schedulable yet.
