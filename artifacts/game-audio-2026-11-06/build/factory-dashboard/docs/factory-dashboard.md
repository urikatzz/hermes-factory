# Factory HTML dashboard

Generate a standalone, read-only HTML snapshot. Open the output in a browser; all assets and data are embedded, with no server or external resources. Regenerate to refresh.

## Live Factory command

Run from the dashboard worktree:

```sh
python3 scripts/generate_factory_dashboard.py \
  --board-db /Users/example/.hermes/kanban.db \
  --board-id default \
  --hermes-home /Users/example/.hermes \
  --published-state /Users/example/.hermes/state/factory/published.json \
  --output reports/factory-live.html
```

## Private sandbox pilot command

```sh
python3 scripts/generate_factory_dashboard.py \
  --board-db /private/tmp/hermes-factory-sandbox-pilot-7/home/kanban/boards/sandbox-pilot/kanban.db \
  --board-id sandbox-pilot \
  --hermes-home /private/tmp/hermes-factory-sandbox-pilot-7/home \
  --evidence-root /private/tmp/hermes-factory-sandbox-pilot-7/state/evidence \
  --output reports/factory-pilot.html
```

Both pilot tasks intentionally appear under Unlinked tasks: no Factory parent was recorded. This report preserves their explicit session links, matching manifest `9b734edbedb2` and finalized sandbox cleanup records.

Only selected input sources are read. The generator does not initialize Hermes, run models, start Docker, change the scheduler, activate sandbox profiles, retry work or publish code. It uses Python 3.11+ standard library. The inspected Hermes schema revision is `9e041a7428392b01b989ef9cecf46a5f96be12fc`.

## Interpreting money and usage

- Known actual spend sums recorded actual USD amounts only.
- Recorded estimates sum available non-included session estimates separately. They are not an invoice or a complete task cost.
- Included means subscription-included usage with no dollar charge supplied. A zero estimate does not establish a free task.
- Coverage counts explicit worker-session links. Unmatched attempts remain unavailable; time/title/PID guesses are not used.
- Shared sessions count once overall and are not apportioned across parents/attempts. A shared attempt shows whole-session counters with a warning.
- Input, output, cache-read, cache-write and reasoning counters are displayed separately. They are not added into an invented total.
- Worker sessions exclude this development conversation, subscription fees, infrastructure costs and unattributed coordinator work. Model prices are not fetched.

## Parent tasks, events and metrics

Parent roots use the installed Factory's `FACTORY:` title convention. Child stages reference the root with a terminal `(t_<hex>)` suffix. All recorded attempts are retained, with status separate from verdict. Done does not imply PASS. Delivery URLs, branch names and manifests are recorded evidence; they do not establish repository checks, merge status or publication success.

The timeline combines persisted board events with identity-matched optional sandbox phases. It is not a complete trace of every agent action. Physical database identity, rather than profile spelling, scopes session deduplication, including case aliases. Source read times are shown; cross-database reads are not globally atomic.

- Card completion: done roots divided by non-archived roots. Archived roots are still inspectable.
- Median completed cycle: creation-to-completion duration of done non-archived roots with valid timestamps.
- Execution retries: extra recorded attempts on child stage cards. A separate FIX stage is not itself an execution retry.
- Failed attempts: explicit failed/blocked/error outcome or failed stage verdict, once per attempt. This is a count of recorded failure evidence, not a failure-rate denominator.
- Missing history, timestamps and cost fields stay unknown rather than becoming zero.

## Validation

```sh
python3 -m unittest discover -s tests/dashboard -p 'test_*.py' -v
node --check factory_dashboard/assets/report.js
```

The suite uses Python unittest plus the installed Node executable for pure JavaScript presentation checks; the generator itself has no Node dependency.

The focused suite exercises real SQLite fixtures, record attribution/aggregation, safe JSON embedding, atomic file publication and CLI behavior. These checks do not substitute for visual/browser testing. Browser inspection availability and execution results are recorded in `docs/factory-dashboard-results.md`.

## Privacy and failures

Output contains local task summaries and paths and is written with mode 0600. Treat it as private project data. The report does not include authentication stores, prompts, session message bodies or environment dumps. Event payloads and summaries can still contain project information.

Missing/unreadable/unsupported required board data fails generation with exit 2, preserving an existing report. Missing optional sources produce warnings and partial coverage with exit 0. A locked source is bounded to a two-second SQLite connection timeout. On an active WAL database, access to its normal SQLite sidecars may require scoped filesystem permission; never use immutable mode to bypass that requirement or copy only its live main database file.

No automatic refresh service or live controls are installed. Durable coordinator recovery and spending-cap enforcement remain separate work.
