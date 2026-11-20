# Known failing test suites

Measured 2026-11-20 with `scripts/run_all_tests.py --baseline 7f32ddb` (the last commit before any reference-authority change) (Hermes Python 3.11.16, PyYAML installed, so no suite is skipped): the same suites run on a clean checkout of that commit and on the working tree, and the failing test ids are compared. **New failures: none.** These six failures exist at the baseline and are unrelated to the reference-authority work; none was touched or hidden.

| Suite | Test | Observed failure |
| --- | --- | --- |
| `tests/art` | `test_lint.LintTests.test_cli_summary_and_bad_path` | `art_lint.py` exits with argparse `unrecognized arguments: ../escape`; the test expects the script's own `not an existing path inside` message |
| `tests/ecc` | `test_migration.MigrationTests.test_partial_conflict_has_receipts_and_resumes_from_fresh_preview` | migration preview reports `4` changes, test expects `2` |
| `tests/ecc` | `test_migration.MigrationTests.test_preflight_size_limits_and_excludes_archived_templates` | migration preview reports `5` changes, test expects `3` |
| `tests/ecc` | `test_migration.MigrationTests.test_service_migration_preserves_defaults_and_history_and_is_idempotent` | migration preview reports `5` changes, test expects `3` |
| `tests/ecc` | `test_migration.MigrationTests.test_stale_preview_and_modified_preview_do_not_write` | template list has five entries (`[2, 1, 1, 1, 1]`), test expects three |
| `tests/factory_art_type` | `test_migration.LiveCopyTests.test_cli_round_trip_on_a_copy_of_the_live_store` | `migrate_game_art: Invalid workflow fields` (copies the live Hermes store, whose workflow documents are newer than the migration expects) |

The four `tests/ecc` failures all assert an exact number of workflow templates (three) while five are now present, which is consistent with the seeded preset templates having grown; they predate this change.

## Proving a change adds no failures

```sh
~/.hermes/hermes-agent/venv/bin/python scripts/run_all_tests.py --baseline 7f32ddb
```

The script runs every suite, prints the failing ids as JSON, and exits non-zero only when `new_failures` is non-empty. `preexisting` lists the table above; `fixed` lists any baseline failure a change repairs.

Result for the reference-authority change:

| Suite | Tests now | Failing now | Tests at baseline | Failing at baseline |
| --- | --- | --- | --- | --- |
| art | 74 | 1 | 74 | 1 |
| audio | 47 | 0 | 47 | 0 |
| ecc | 33 | 4 | 33 | 4 |
| factory_art_type | 34 | 1 | 34 | 1 |
| production | 43 | 0 | 43 | 0 |
| secrets | 12 | 0 | 12 | 0 |
| workflow_v2 | 229 | 0 | 155 | 0 |

`workflow_v2` gained 74 tests (reference authority, inspection proof, role-specific findings, art-plan gate and mockup, holistic review, art-reviewer controller flows, orchestrator exposure, implicit deferral, derived sources, end-to-end regression, project-agnostic checks).
