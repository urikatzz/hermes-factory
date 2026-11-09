# Workflow mutation coverage

Managed identity is the board's root/stage registry and immutable sidecar binding. Titles never confer authority. The generic synchronous guard runs under the mutation's write transaction; required consumer acknowledgements persist with the board.

| Entry routes | Transactional enforcement owner |
| --- | --- |
| CLI, tools, ordinary dashboard create | `kanban_db.create_task`, creation hook receives transaction; created guard holds root and acknowledges required policy |
| Claim / review claim / retry | `claim_task`, `claim_review_task`, `reclaim_task`; `claimed` binds actual run ID |
| Complete / force / review / request changes | `complete_task`, `request_review`, `request_changes`; root completion exclusively controller-owned |
| Assign / provider / model / effort | `assign_task`, `_set_task_override`; captured stages refuse changes |
| Title/body edits | `edit_task`; title/priority allowed, execution body/results immutable |
| Dashboard direct patch/status | `plugin_api._patch_title_body`, `_set_status_direct` call generic guard |
| Dependencies / decomposition | link/unlink/internal-link, descendant invalidation, `decompose_triage_task` |
| Bulk operations | Same guarded per-task owners; transaction veto preserves rows |
| Block / unblock / promote / reopen / specify / schedule | Guarded owners; current stage may report blockage, controller owns resume |
| Archive / delete / deleted archive | Guarded owners; cannot bypass gate by removing a required card |
| Swarm activation | Guard before inline activation writes |
| Scheduler automatic readiness | Established sticky blocked event holds controller root; guarded claims refuse root execution regardless |
| Portable export/import | Reject boards with required mutation policies before identity scrubbing; sidecar state is not portable |
| Native task referencing managed root in title | Remains native in creation and frozen resolver; no captured role attached |
| Missing workflow plugin | Required policy acknowledgement fails closed; activation additionally checks installed consumer identity and version |

Controller writes to its own registry and root terminal state are intentionally not public mutation APIs. Trusted scope is an in-process ContextVar bound to the exact board connection and root, never a request flag. Root delivery produces no fabricated worker attempt. Source snapshot and publishing commands remain local evidence, not executed commands.

Worker-launch evidence uses the durable `spawned`/`worker_registered` event for the accepted run, because process cleanup can clear a historical PID. Worker summaries alone cannot establish ownership.

Generic board removal remains an explicit board-level administrative action, not a workflow delivery path. Raw SQLite editing is outside supported task APIs and can corrupt the system, as before.
