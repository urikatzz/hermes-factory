# Multi-board Factory: one Hermes board per run

Ticket intake stays on the `default` board. Every new factory run gets its own Hermes board, which holds the workflow root, stage
and worker cards, findings, approvals and retries. Existing roots on `default` are untouched and keep working.

## Architecture

| Piece | Where | Job |
|---|---|---|
| Board registry | `factory_dashboard/board_registry.py`, DB `~/.hermes/state/factory/board-registry.db` | One row per run board: ticket, project, workflow, board id, database path, root, status, attempts, last error. Unique per ticket, per database path, and per live `project_dir` / `branch`. |
| Board resolver | `BoardResolver` in the same module | The only authority on which boards the Factory governs: the configured default board plus registered run boards. Path is authoritative; labels only catch mixups. Unregistered boards resolve to `None` and are never touched. A registered board with a wrong path/label, or a `failed` board, raises an error that names the cause and the fix. |
| Provisioning | `factory_dashboard/run_boards.py` (`RunBoards.provision`) | `reserve → create Hermes board → initialize schema → activate`, each step idempotent. A failure is counted in the registry; after 3 attempts the board is `failed` and fails closed until `factory_boards.py reset`. |
| Plugin hooks | `integrations/hermes_factory_models/__init__.py` | Creation guard, model resolver, mutation guard and reconcile now ask the resolver. Every board reconciles alone (dispatch tick carries the board slug), so one board's failure, pause or recovery never touches another. |
| Settings snapshots | `task_settings_store.bind_task(..., source_board=)` | A run board's root inherits its ticket's frozen snapshot (captured on the intake board) and is bound under the run board's own identity; stage cards bind the same way. Nothing else may bind across boards. |
| Intake | `runtime/factory-scripts/factory_intake.py` | With `dedicated_boards: true` in `state/factory/config.json` each ticket provisions its board, creates the root there (idempotency key `intake-<ticket>`), binds it in the registry, then closes the ticket. Capacity (`max_roots`, `max_roots_per_repo`) counts roots on every board. |
| Other cron scripts | `factory_alerts/publish/watchdog/resume_rate_limit/status` | Fan out one isolated process per registered board (own state files), then handle `default` as before. |
| Dashboard | `runs_service.py`, `runs_http.py`, `assets/runs.{html,js}` | `/runs` page, `GET /api/runs`, `GET /api/runs/<board>`, `POST /api/runs/<board>/{pause,resume,cancel,archive}` (same local-origin + token protection as other writes). |
| Kanban plugin | `runtime/kanban-plugin` | The board switcher shows `⚑ N awaiting approval` per board. The Awaiting-approval column itself already works on any selected board. |

## Isolation guarantees

* Own database, workspaces, attachments, logs and dispatcher tick per run (Hermes boards).
* Workflow state, repair budgets, findings, approvals and decisions live in the run board's database.
* Model policy is a frozen snapshot per ticket, bound under the run board's identity; a snapshot can only cross boards when the registry names the source board.
* A run board accepts exactly one root (`intake-<its ticket>`); tickets, other roots, and a second root on the intake board for a ticketed run are refused.
* `project_dir` and `(project, branch)` are exclusive across live runs.
* Duplicate dispatch is prevented by Hermes' atomic claim within a board plus the controller's `(root, stage, cycle, retry)` uniqueness; one ticket can never own two boards.

## Operating

```
factory_boards.py list [--all] [--json]       # all runs: status, phase, awaiting approval
factory_boards.py show BOARD                  # blockers, active stages, counts
factory_boards.py pause|resume|cancel|archive BOARD [--reason R]
factory_boards.py reset BOARD                 # give a failed board a fresh provisioning budget
factory_boards.py resolve --db PATH [--label SLUG]
resume_factory_workflow.py --board-db <run board db> --board <slug> ...   # stage repair; refused unless the run is active
```

Use the Hermes venv python. `pause` parks queued cards (running workers finish their attempt); `resume` restores them;
`cancel` blocks open cards and stops the root; `archive` moves a finished, cancelled or failed board to `boards/_archived/` and keeps it
readable from the dashboard.

## Activation interlock

`dedicated_boards` only takes effect once the running gateway has loaded this plugin (the plugin writes
`state/factory/board-support/<pid>` on load; intake checks the pid in `gateway.pid`). Until then intake keeps creating legacy roots on
`default` and records `waiting-for-gateway-restart` in `state/factory/board-activation.json`. After the next gateway restart it switches by itself
and records `active`. A gateway running older code can therefore never receive a board it would not govern.

## Rollback

1. Set `dedicated_boards` to `false` (or remove it) in `state/factory/config.json`: new roots go back to `default` immediately.
2. Existing run boards keep working while the plugin is loaded. To retire them: finish or `cancel` each, then `archive`.
3. To restore the previous code, copy back the backup taken before deployment (`~/.hermes/backups/multi-board-<stamp>/`: `config.yaml`, `scripts`, `factory-dashboard`, `plugins-factory-models`, `profiles-plugins`, `hermes-agent-kanban-plugin`, `state`, `kanban.db`, `boards`) and restart the gateway when no task is running. The registry database is only read by the new code; the old code ignores it.
