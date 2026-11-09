# Factory HTML Snapshot Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development only if the user selects delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a local HTML report showing Factory parent tasks, attempts, events, blockers, attributable session usage/cost, delivery records, and defined throughput metrics.

**Architecture:** Read explicitly selected local sources through a collection service, build a normalized report through a separate aggregation service, then render it into a standalone HTML file. No server, live workflow changes, or inferred billing attribution. The installed Factory and the sandbox worktree remain unchanged.

**Tech Stack:** Python 3.11+ standard library (`sqlite3`, `json`, `dataclasses`, `statistics`, `unittest`); plain HTML/CSS/JavaScript; existing browser tooling for visual inspection.

**Spec:** `docs/superpowers/specs/2026-10-16-factory-dashboard-design.md` (user approved 2026-10-16).

## Global Constraints

- No application server, build toolchain, external CDN, remote model calls, or live database mutations.
- Support inspected Hermes revision `9e041a7428392b01b989ef9cecf46a5f96be12fc`; validate required schema before querying.
- SQLite uses read-only connections and a read transaction per database. Do not use immutable mode against active WAL databases, run migrations, enable extensions, or invoke Hermes CLI methods that could initialize or update databases.
- Only explicit `task_runs.metadata.worker_session_id` and the run's profile establish a session link; never use originating `tasks.session_id` or time/title/PID guesses.
- A null actual cost is unknown. Included usage with zero estimate is not a $0 actual charge. Known actual and estimated totals are separate and display coverage.
- Deduplicate sessions by profile database plus session ID. Shared sessions are counted once overall and never allocated by guess to parents or attempts.
- Never read credentials, session prompts/messages, raw environment variables, or project files. Metadata never supplies filesystem input paths.
- Render record text as text nodes, escape embedded JSON script delimiters, allow only parsed HTTP/HTTPS delivery links, and make no external requests when viewing.
- Write output atomically with owner-only permissions. A collection/render failure preserves the previous report.
- No live activation, schedulers, spending-cap enforcement, recovery controls, commits, or pushes. Ask separately before committing or pushing.
- Focused automated checks and browser inspection are proposed below for explicit approval with this plan; no dashboard tests have been added or run during planning.

## Review Focus

1. Shared session links across roots or profiles must not double-count spend or expose another profile through a malicious profile path (Tasks 1/2).
2. A done stage with FAIL and an archived root must not inflate verified-delivery or completion metrics (Task 2).
3. Concurrent WAL writers, database locks and failed optional sources must yield a coherent per-source read or an explicit warning/error, never an empty-success report (Tasks 1/4).
4. Malformed metadata, sandbox identity mismatch and symlinked evidence must not introduce false attribution or unrequested file reads (Tasks 1/2).
5. Hostile task text, script-closing JSON and unsafe delivery URLs must remain inert in an offline file and not break browser filtering/navigation (Tasks 3/4).

## Files and interfaces

Create an isolated feature worktree at execution time using `superpowers:using-git-worktrees`; copy the approved untracked spec/plan into it. Retain a final sample under the user's Hermes workspace for an accessible delivery link. Do not mix this feature into `/private/tmp/hermes-factory-sandbox`.

| File | Responsibility |
| --- | --- |
| `factory_dashboard/__init__.py` | Package marker |
| `factory_dashboard/models.py` | Immutable `SourcePaths` and `Snapshot` records |
| `factory_dashboard/collector.py` | Read-only source collection and diagnostics |
| `factory_dashboard/report.py` | Parent grouping, usage attribution, timelines, metrics |
| `factory_dashboard/renderer.py` | Safe report embedding and atomic output |
| `factory_dashboard/assets/report.html` | Page shell and controls |
| `factory_dashboard/assets/report.css` | Dark responsive layout and focus states |
| `factory_dashboard/assets/report.js` | Local filtering, selection and safe DOM rendering |
| `scripts/generate_factory_dashboard.py` | CLI composition; no import-time work |
| `tests/dashboard/fixtures.py` | Small synthetic SQLite/JSON fixture builders |
| `tests/dashboard/test_collector.py` | Source reading and boundary checks |
| `tests/dashboard/test_report.py` | Attribution and metric checks |
| `tests/dashboard/test_renderer.py` | Serialization/output checks |
| `tests/dashboard/test_cli.py` | Full generation and failure behavior |
| `docs/factory-dashboard.md` | Generation commands, definitions and limits |
| `reports/factory-pilot.html` | Generated private-pilot sample; no credentials/prompts |

`SourcePaths(board_db: Path, board_id: str, hermes_home: Path, published_state: Path | None, evidence_root: Path | None)` contains user-selected input locations. Optional arguments identify genuinely optional sources, not fallbacks for required dependencies.

`Snapshot(board_id: str, generated_at: str, sources: tuple[dict, ...], tasks: tuple[dict, ...], runs: tuple[dict, ...], events: tuple[dict, ...], sessions: tuple[dict, ...], published: dict, evidence: tuple[dict, ...], warnings: tuple[dict, ...])` contains whitelisted records only. Each session includes its source database identity and profile; each source includes path/read time/status. Read columns by explicit name; never select prompt/body/model_config payloads wholesale.

`SnapshotCollector(source_paths: SourcePaths).collect() -> Snapshot` raises `SourceReadError` for an unusable required board and produces warnings for unavailable optional inputs.

`ReportBuilder().build(snapshot: Snapshot) -> dict` returns schema version 1 with `board`, `generated_at`, `sources`, `warnings`, `summary`, `parents`, `unlinked_tasks`, `shared_sessions`, and `coverage`. Parent/task entries contain their IDs, state/verdict, attempts, timeline, usage, artifacts and delivery. Missing numeric values remain JSON null.

`HtmlRenderer(asset_root: Path).render(report: dict) -> str` embeds assets/data; `write_report(output_path: Path, content: str) -> None` atomically publishes it.

CLI: `python3 scripts/generate_factory_dashboard.py --board-db PATH --board-id ID --hermes-home PATH --output PATH [--published-state PATH] [--evidence-root PATH]`. No implicit archived-board discovery or installed-state defaults. Exit 0 means generated (including disclosed optional-source warnings); exit 2 means required source/configuration failure, with a concise stderr diagnostic.

## Task 1: Collect selected records without changing the Factory

**Files:** Create package marker, `models.py`, `collector.py`, fixture builders and `test_collector.py`.

**Interfaces:** Produces `SourcePaths`, `Snapshot`, `SourceReadError`, and `SnapshotCollector.collect()` as defined above.

- [ ] Add failing checks: required missing board raises without creating a file; unsupported required columns raise; optional missing session columns preserve available fields and emit a warning; malformed JSON metadata/events become visible invalid-record warnings.
- [ ] Add failing boundary checks: profile `../other` cannot escape the selected home; default profile resolves only to selected `home/state.db`, named profiles only to `home/profiles/<profile>/state.db`; symlinked profile databases/evidence and mismatched evidence board/task/run IDs are rejected or warned rather than attributed.
- [ ] Add failing SQLite checks: active WAL fixture includes committed records; collection does not change table contents or schema; required-source lock fails clearly using a bounded 2-second connection timeout; an optional locked session source produces a warning.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p test_collector.py -v`; confirm new behavior fails for the missing implementation.
- [ ] Implement schema inspection and explicit whitelisted SELECTs in read transactions. Read only profile databases referenced by runs. Keep per-source read timestamps and sanitize diagnostics to source identity/error class rather than record contents. Parse optional published JSON and evidence only within selected locations, without following links or opening `result_path` from evidence.
- [ ] Run the same collector command; require all checks passing before Task 2. Record commands/outcomes in the execution ledger; do not commit.

## Task 2: Build trustworthy parent, timeline, usage and metric views

**Files:** Create `report.py`, `test_report.py`; extend fixture builders.

**Interfaces:** Consumes `Snapshot`; produces version-1 report dictionary via `ReportBuilder.build()`.

- [ ] Add failing assertions for exact `FACTORY:` roots and terminal `(t_<hex>)` child suffixes, orphan/unrecognized tasks in `unlinked_tasks`, stable stage/attempt order, and a done card retaining its FAIL/BLOCKED/CHANGES_REQUIRED verdict.
- [ ] Add failing assertions for explicit worker-session join only, missing links decreasing coverage, identical session IDs in different profiles remaining distinct, and one session linked to two runs being counted once overall with no fabricated per-parent allocation.
- [ ] Add failing assertions for Included with null actual/zero estimate, separate actual/estimated partial totals, missing token fields staying null, and separate cache/reasoning counters without an invented total-token sum.
- [ ] Add failing assertions: archived roots excluded from card-completion denominator; empty denominator returns null; completed root intervals 10/30 seconds yield median 20; invalid/negative intervals excluded with warning; three attempts on one stage yield two retries while a FIX stage is counted separately.
- [ ] Add failing assertions for recorded event timestamp ordering with deterministic ties; missing timestamps remain visibly unknown; sandbox phases join only on the selected board/task/run; delivery URL and branch are recorded evidence rather than inferred merge/check success. Failure totals count attempts with explicit failed outcome or failed verdict once; a failed verdict without an attempt is a separate stage-verdict count.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p test_report.py -v`; confirm failure for missing behavior.
- [ ] Implement aggregation using explicit IDs and source identities. Include root's own recorded attempts/usage in parent detail alongside child stages. Parse anchored `VERDICT=` summaries and recognized stage/cycle labels; keep raw unrecognized titles/outcomes visible. Emit coverage counts alongside totals; zero linked sessions yields unavailable totals rather than complete $0.
- [ ] Run the same report checks and Task 1 checks; require passing results and inspect a fixture's report dictionary for the defined fields. Do not commit.

## Task 3: Render an offline HTML dashboard

**Files:** Create `renderer.py`, the three asset files and `test_renderer.py`.

**Interfaces:** Consumes version-1 report; produces HTML through `HtmlRenderer.render()` and atomic owner-only output through `write_report()`.

- [ ] Add failing assertions that rendering embeds all assets without external `src`, stylesheet URLs or fetch calls; hostile `</script>`, quotes and Unicode survive JSON decoding without generating executable markup; optional URLs admit only HTTP/HTTPS after parsing.
- [ ] Add failing output assertions: an existing report survives simulated render/write failure; a published file is mode 0600; missing parent output directory is created under the supplied destination; no temporary output remains after failure.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p test_renderer.py -v`; confirm failure for the missing renderer.
- [ ] Implement a single JSON data block with `<`, `>`, `&` and Unicode line separators escaped; trusted asset insertion uses fixed template placeholders. Set record text only through DOM `textContent`; create approved links with safe parsed URLs and `rel=noopener noreferrer`. No record-derived HTML or inline handlers.
- [ ] Implement header/provenance, status/spend/coverage summary, searchable/status-filtered parent list, selected task/attempt details, recorded timeline, artifacts, shared sessions, unlinked tasks and source warnings. Provide empty/filter-no-results states, keyboard selection/focus, responsive stacked details, and recorded-vs-verified labels. Use Included / dollar amount unavailable and Usage unavailable consistently.
- [ ] Run renderer, collector and report checks. Browser behavior and responsive layout are verified in Task 4; static assertions alone do not establish browser safety/usability. Do not commit.

## Task 4: Deliver the generator and inspect real reports

**Files:** Create CLI, `test_cli.py`, `docs/factory-dashboard.md`, and generated `reports/factory-pilot.html`.

**Interfaces:** Composes prior services through the defined CLI. No Hermes imports, model tasks, Docker operations or installed-state writes.

- [ ] Add failing CLI assertions: a valid synthetic board exits 0 and produces the report; optional source failure exits 0 with report warnings; missing/incompatible board exits 2 with no successful replacement; malformed CLI paths produce a concise diagnostic. Assert synthetic reports preserve done/FAIL, shared session and unknown-dollar labels.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p test_cli.py -v`; confirm failure before implementing CLI composition.
- [ ] Implement `main(argv: list[str] | None = None) -> int` in the CLI, injecting required collector/builder/renderer dependencies by construction. Write usage documentation with metric definitions, snapshot staleness, billing scope, incomplete history, privacy, and exact regeneration commands.
- [ ] Run `python3 -m unittest discover -s tests/dashboard -p 'test_*.py' -v`; require zero failures. No sandbox regression suite or model rerun is needed because its files/runtime are unchanged.
- [ ] Generate `reports/factory-pilot.html` from board `/private/tmp/hermes-factory-sandbox-pilot-7/home/kanban/boards/sandbox-pilot/kanban.db`, board ID `sandbox-pilot`, Hermes home `/private/tmp/hermes-factory-sandbox-pilot-7/home`, and evidence root `/private/tmp/hermes-factory-sandbox-pilot-7/state/evidence`. Verify both pilot tasks remain unlinked, with explicit worker sessions, their recorded token counters, Included labels, matching manifest `9b734edbedb2`, and cleanup records. No inferred parent is created.
- [ ] Generate a separate report from a synthetic multi-parent fixture for UI inspection. Open generated reports with the available browser tool; inspect at desktop and narrow width, exercise search/filter/selection/keyboard navigation, confirm hostile text is inert and no remote resource is requested. Use the existing browser tools without installing browser dependencies. Record any behavior the available tools cannot verify.
- [ ] Attempt a read-only real-board report with explicit board `/Users/example/.hermes/kanban.db`, board ID `default`, selected home `/Users/example/.hermes`, and published state `/Users/example/.hermes/state/factory/published.json`, writing output into the feature workspace. If sandbox permissions block SQLite WAL access, request scoped tool escalation for that concrete generation command; do not change connection semantics or copy a live main database without its WAL. A failed real-board read must be reported and does not erase the successful private-pilot sample.
- [ ] Review the complete implementation against the spec; use the native workflow's final reviewer only if authorized by the selected workflow. Resolve material findings and repeat affected checks. Record exact evidence, remaining limitations, and final report location. No commits/pushes/installation.
- [ ] Copy the final generated sample to `/Users/example/orca/projects/hermes/reports/factory-pilot.html` for delivery if implementation used a temporary worktree. Deliver the sample and generation command with known coverage; do not call the other Factory gaps implemented.

## Self-review and execution handoff

Coverage: source/provenance/failure boundaries → Task 1; parent/attempt/timeline/billing/metrics → Task 2; offline accessibility/safe rendering → Task 3; CLI/private-pilot/real-board reporting and documentation → Task 4. All five Review Focus cases have checks in their owning tasks. Interface names and version-1 field names agree across tasks.

Proposed execution: native, because collection, aggregation and rendering share a small report contract and can be implemented in sequence without implementer-agent overhead. This plan includes focused automated verification and browser inspection for approval; no tests or product code have been written during planning. The Superpowers writing-plans workflow requires user review of this plan and confirmation of execution method before implementation begins.
