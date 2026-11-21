# Hermes patches

The Factory needs a few local changes to the Hermes source tree. A Hermes update resets that tree to an upstream commit, which removes them
silently: stage creation then fails on a missing module, and an unknown hook name is only logged as a warning. They are kept here as plain
git patches against upstream, so they survive updates and can be reapplied.

| Patch | What it carries |
| --- | --- |
| `patches/0001-factory-kanban-core.patch` | `kanban_db_mutation_guard`, `kanban_db_task_creation`, `kanban_db_worker_model`, their wiring in `kanban_db*.py`, `kanban_swarm.py`, `kanban_transfer.py`, and the hook names (`resolve_kanban_worker_model`, `before_kanban_task_create`, `before_kanban_task_mutation`) in `plugins.py` |
| `patches/0002-kanban-dashboard-plugin.patch` | The kanban dashboard's awaiting-approval column and run-board aware API |

`manifest.json` lists the files each patch produces with their sha256 and the upstream commits the set was verified with.

```sh
python3 runtime/hermes-patches/hermes_patches.py status          # exit 0 all applied, 1 missing but appliable, 2 conflict
python3 runtime/hermes-patches/hermes_patches.py apply --dry-run
python3 runtime/hermes-patches/hermes_patches.py apply           # backs up replaced files, rolls back on any failure
```

`apply` only acts when every missing patch applies cleanly. It never merges. Restart the Hermes gateway afterwards: a running gateway keeps the code it loaded.

## After a Hermes update

1. `status`. If everything is `applied`, restart the gateway if it started before the update finished.
2. `missing`: run `apply`, then restart the gateway.
3. `conflict`: upstream changed the code around a patch. In a scratch worktree of the new upstream:
   ```sh
   git -C ~/.hermes/hermes-agent worktree add /tmp/hermes-merge HEAD
   cd /tmp/hermes-merge && git apply --3way ~/path/to/runtime/hermes-patches/patches/0001-factory-kanban-core.patch   # resolve the conflict markers
   # run the factory suite against it: PYTHONPATH=runtime/factory-dashboard:/tmp/hermes-merge python3 -m unittest discover -s tests/workflow_v2
   python3 runtime/hermes-patches/hermes_patches.py export --tree /tmp/hermes-merge
   python3 runtime/hermes-patches/hermes_patches.py apply
   ```
   Commit the regenerated patches and manifest.

## Automatic detection

- The Factory plugin checks for the patches when it loads (`factory_dashboard/hermes_compat.py`), logs an error naming what is missing, and does not claim run-board support.
- `runtime/factory-scripts/factory_patch_check.py` is a cron job (no agent). It records `state/factory/hermes-patches.json`, prints one message when the situation changes, and the intake pump starts no new work while patches are missing. It also applies clean patches itself (`--check-only` turns that off), but only after the problem has persisted for two minutes, never while a Hermes update is running, and never over a conflict. It does not restart the gateway.

Install the set where the cron job finds it: `cp -R runtime/hermes-patches ~/.hermes/hermes-patches` (or set `HERMES_PATCHES_DIR`).

## 0003-owner-applies-worker-model

The dispatcher captures the model chosen for an attempt in the run's metadata (`worker_model_selection`), but the profile owner (`gateway/session_kanban.py build_kanban_policy`) rebuilds the session policy from the task row, which does not carry it, so workers silently ran each profile's default model. The patch applies the captured selection (model, provider, effort) to the policy and refuses the claim when the selection is malformed. Nothing else in the owner path or any profile configuration changes.

`probe_owner_model.py` proves the behavior rather than the patch text: it builds a throwaway board and profile, runs the owner's own policy builder and reads the model it picked (selection applied, default untouched without one, malformed refused). `factory_patch_check.py` runs it per Hermes head and reports patches that are applied but do not work.

