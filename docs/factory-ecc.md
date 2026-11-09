# Factory research guidance and benchmark

Factory now has a selective ECC adaptation: captured research/context instructions and an offline benchmark toolkit. Python 3.11+ standard library is sufficient for benchmarking. Template migration additionally uses the installed Factory dashboard Python package.

## Worker behavior

Preparation searches the assigned repository for existing implementations and extension points. When relevant and permitted, it checks external documentation or registries. PLAN.md records inspected paths, alternatives, the selected approach and missing context. Unavailable search tools are recorded honestly.

Preparation, implementation and repair use at most three search refinement rounds before reassessing gaps. Necessary reading can continue afterward; missing requirements are never guessed. These instructions live in workflow template revisions. A task captures them at submission, so existing tasks and repairs retain their prior instructions. The worker contract, review panel, repair limits and model defaults remain authoritative.

## Benchmark commands

From this project directory:

```sh
python3 scripts/factory_benchmark.py taskset --taskset benchmarks/factory-v1
python3 scripts/factory_benchmark.py prepare \
  --taskset benchmarks/factory-v1 --case bug --output /private/tmp/my-bug-trial
python3 scripts/factory_benchmark.py grading \
  --taskset benchmarks/factory-v1 --case bug \
  --candidate /private/tmp/my-bug-trial/source --output /private/tmp/my-bug-grading
python3 scripts/factory_benchmark.py report \
  --taskset benchmarks/factory-v1 \
  --results benchmarks/factory-v1/examples/results.json \
  --evidence-root benchmarks/factory-v1/examples \
  --output /private/tmp/factory-benchmark-example
```

`prepare` copies baseline source and public task instructions only. Hidden graders and expected results stay outside worker inputs. `grading` creates separate candidate/trusted directories and a pinned grading identity; it executes nothing. `report` writes private `<output>.json` and `<output>.md` files after validating inputs. Outputs cannot overwrite consumed taskset/evidence files or enter a candidate source directory. Invalid inputs preserve existing reports; the two output replacements are individually atomic, not one cross-file transaction.

The supplied example is synthetic and checks report mechanics only. It contains no measured model performance. For the chore case, baseline behavior intentionally passes the regression checks; the reviewer must assess whether the requested simplification actually occurred.

## Running real trials

1. Select a private disposable Factory board/home and explicit workflow/model/provider/effort settings for each variant. Capture the full workflow definition and role settings from the submitted task, not current defaults. Use a new root for every independent trial.
2. Prepare one case per trial. Read `task.json` for the prompt and acceptance criteria. Give workers only its source directory and public instructions. Keep grader files and answers outside that workspace.
3. Confirm that every participating profile uses the approved sandbox path before submitting work. The archived sandbox pilot demonstrates IMPLEMENT/VERIFY routing only; it does not establish full managed-graph sandbox coverage. Do not enqueue trials on the production board to test this toolkit.
4. Retain the reviewed candidate source, completed run identities, acceptance evidence, final controller gate event and captured settings. Use the same final implementation manifest for all selected reviewers and the verifier.
5. Prepare grading inputs. Within the approved disposable runtime, run `python3 trusted/grader.py candidate trusted/job.json` with a ten-second timeout, 256 MiB memory, one CPU and 64 PIDs. These limits must be enforced by the supervisor, not trusted to candidate code. Retain the resulting JSON as grade evidence.
6. Review grading provenance and normalize the evidence into the formats below. The simple functional graders import candidate code into their Python process: they are not tamper-resistant judges. A hostile candidate can interfere with them. Do not grant automatic promotion/merge authority based on these grades. Evidence files are operator-selected local records; hashes validate byte identity, not independent authenticity.
7. Run `report` over the retained local evidence. Use repeated independent trials before drawing model/workflow conclusions; the report makes no statistical superiority claim.

No command here launches models, schedules paid work, exports credentials, or executes worker-supplied commands on the host. Full graph execution automation and evaluation promotion gates are deferred.

## Pinned taskset and evidence formats

`taskset.json` uses `factory-ecc-taskset/v1`, a positive version, three case definitions, source/grader file hashes and a SHA256 digest of the canonical JSON document without its digest field. Updating any prompt, acceptance criterion, baseline or grader requires a new taskset version/digest. The baseline and grader bytes must match their hashes.

Results use `factory-ecc-results/v1`. See `benchmarks/factory-v1/examples/results.json` for an exact complete example. Required fields are:

| Field | Meaning |
|---|---|
| `taskset_digest` | Pinned taskset digest |
| `synthetic` | Explicit boolean applying to the entire result set; never mix synthetic and real trials |
| `variants` | Unique IDs, full captured workflow definitions and all selected profiles' provider/model/effort settings |
| `trials` | Unique `(variant_id, case_id, trial_id)` records with a distinct Factory root per trial |

Each trial has `board` (an explicitly scoped board identity), `root_id`, `writer_run_id`, `manifest_sha256`, `candidate_source`, `terminal_outcome`, `repairs`, `elapsed_seconds`, `evidence` and `sessions`. Root/run identities, candidate/manifest, repairs and duration may be null when not recorded; null evidence cannot prove success. Outcomes are `completed`, `failed`, `infrastructure_blocked` or `incomplete`.

`candidate_source` is a relative directory containing only the retained deliverable source used for grading. Its manifest is SHA256 of canonical JSON mapping sorted relative file paths to their SHA256 contents. This is distinct from Factory's native `manifest_sha12` derived from SHA256SUMS. The gate envelope links both explicitly. Do not include unrelated caches or generated grader output in the candidate tree.

`evidence` contains `grades` and `gate`, each null or `{ "path": "relative/file.json", "sha256": "<64 lowercase hex>" }`. Paths resolve under the explicit evidence root. Traversal, symlinks, oversized files, duplicate JSON keys, unknown schema fields and nonfinite/negative measurements are rejected.

Grades use `factory-ecc-grades/v1`: taskset/case/source-manifest/grader identity, acceptance IDs and deterministic `ac_results` (`pass`/`fail`). The pinned grader produces this form. Keep its digest and grading provenance with the retained record.

Gate envelopes use `factory-ecc-gate/v1`. The examples contain the exact envelope shape. Normalize the final native `factory_workflow_events` gate document into `decision` (`decision`, `reason`, `blocking`, `waived`); copy `captured_variant` from the task snapshot. Add board/root identity, `source_manifest_sha256`, native `factory_manifest_sha12`, recorded `repairs_used`, accepted writer/verifier/reviewer records, and complete writer attempt history when available. The toolkit does not manufacture this envelope from a card's status.

Each stage record includes `profile`, `task_id`, `run_id`, `outcome`, `verdict`, `manifest_sha12`. Verifier additionally includes `ac_results`. Copy accepted completed run evidence; independent actors require distinct task/run identities. `attempts_complete` must be false unless the entire writer/repair attempt history is retained. `writer_attempts` records each task/run/outcome, including failed attempts. A zero-repair task with execution retries is not a first-attempt success.

## Rates and accounting

The report shows imported trials for every defined case, including zero for unrun cases. Eventual success divides successes by successes plus failed evaluations. Blocked and incomplete trials are displayed beside that denominator. First-attempt success uses only trials with known attempt evidence; missing history is unknown. A completed card without matching source, grade and full selected review/verifier evidence is incomplete unless retained evidence affirmatively establishes failure. Known source/acceptance or stage failures remain failures even when other evidence is unavailable; missing-evidence coverage is reported separately. Success always requires the complete selected panel and matching grades/source. Contradictory records for the same task/run are rejected.

Each linked usage session requires a globally scoped `id`, `actual_usd`, `estimate_usd`, `included`, and five separate nullable token counters: `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`. Scope IDs by physical store/profile/session identity, not a bare local session number. Conflicting values for one ID are errors.

Shared sessions count once overall. Sessions shared across variants are excluded from variant costs and listed explicitly. Actual USD and estimates are separate; included-session estimates are excluded. Known-session counts and trials without session links accompany the sums. Missing costs are unknown, not zero. Coordinator, subscription and infrastructure costs are outside recorded worker usage.

## Guidance preview, activation and rollback

```sh
python3 scripts/migrate_factory_ecc.py \
  --dashboard-source /Users/example/.hermes/factory-dashboard \
  --settings-db /Users/example/.hermes/state/factory/task-settings.db \
  --output /private/tmp/ecc-preview.json
python3 scripts/migrate_factory_ecc.py \
  --dashboard-source /Users/example/.hermes/factory-dashboard \
  --settings-db /Users/example/.hermes/state/factory/task-settings.db \
  --apply-preview /private/tmp/ecc-preview.json \
  --receipt-dir /private/tmp/ecc-new-private-receipts \
  --output /private/tmp/ecc-applied.json
```

Preview validates every active template and shows exact instruction changes. Apply requires that exact preview to remain current. It saves one template at a time through the existing optimistic service; a concurrent edit can stop later saves. Private receipts contain the exact before/after definitions. A fresh preview resumes remaining work. Already migrated templates receive no duplicate block/revision. Unrecognized or edited managed blocks require manual review.

Use a new receipt directory for each apply. A `prepared` receipt can survive process interruption after a save: compare its `after` document to the current head to determine whether that save committed. Never infer completion from a missing result file.

Restore one unchanged migrated template with:

```sh
python3 scripts/migrate_factory_ecc.py \
  --dashboard-source /Users/example/.hermes/factory-dashboard \
  --settings-db /Users/example/.hermes/state/factory/task-settings.db \
  --rollback-receipt /absolute/private/receipts/TEMPLATE_ID.json \
  --output /private/tmp/ecc-restored.json
```

Rollback saves a new revision and refuses to overwrite later template edits. It does not restore an old database, erase task snapshots or rewrite historical revisions.

## Checks

```sh
python3 -m unittest discover -s tests/ecc -p 'test_*.py' -v
python3 tests/ecc/check_graders_live.py \
  --sandbox-source /private/tmp/hermes-factory-sandbox \
  --output /private/tmp/ecc-grader-checks.json
```

The live grader check uses Docker and the already installed Factory runtime image. It makes zero model calls. The sandbox source archive and hashes are retained under `artifacts/factory-ecc-2026-10-19/`; extract it into a fresh temporary directory if the original temporary source is gone.

#### Scenario: Existing functionality can be reused

- **GIVEN** a requested behavior already has an implementation
- **WHEN** preparation inspects the repository
- **THEN** PLAN.md identifies the relevant code and extension point
- **AND** explains the chosen approach using that evidence.

#### Scenario: Guidance changes after submission

- **GIVEN** task A captured revision 1
- **WHEN** the migration creates revision 2
- **THEN** A and its retries keep revision 1
- **AND** subsequent submissions capture revision 2.

#### Scenario: Evidence is unavailable

- **GIVEN** a completed trial lacks retained grading or selected review evidence
- **WHEN** its results are imported
- **THEN** it remains incomplete
- **AND** no missing cost or acceptance result becomes zero or passing.

## Sources

Original Factory instructions and code adapt concepts from ECC's [search-first](https://github.com/affaan-m/ECC/blob/main/skills/search-first/SKILL.md), [iterative retrieval](https://github.com/affaan-m/ECC/blob/main/skills/iterative-retrieval/SKILL.md) and [evaluation harness](https://github.com/affaan-m/ECC/blob/main/skills/eval-harness/SKILL.md). No ECC implementation or skill text was copied, and ECC is not a runtime dependency.
