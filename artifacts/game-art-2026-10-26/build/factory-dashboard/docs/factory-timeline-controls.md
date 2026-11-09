> Superseded by [Factory task snapshots results](factory-task-snapshots-results.md): timelines are read-only and defaults now apply only to new tasks.

# Factory timeline and model controls

The local dashboard shows one lane per agent, recorded execution intervals, separate attempts, and an inspector for status, verdict, observed model, timing and usage. Click a model beneath an agent to edit its saved default. Use **Set model for all agents** for a parent-task override; **Use agent defaults** clears that override. Saving does not change any running or completed attempt.

## Run the demonstration

From the dashboard source directory:

```sh
python3 scripts/serve_factory_dashboard.py --demo --policy-db /private/tmp/hermes-timeline-demo/models.db --port 4610
```

Open http://127.0.0.1:4610 . This is labeled illustrative data. The selectors persist demonstration configuration, and no agent is launched.

## Read the actual board with staged configuration

Export a credential-free catalog using an interpreter with the installed Hermes dependencies:

```sh
/path/to/hermes/python scripts/export_factory_model_catalog.py \
  --hermes-source /path/to/hermes-agent \
  --profile architect --profile developer --profile codex-reviewer \
  --profile claude-reviewer --profile verifier --profile factory-orchestrator \
  --output /private/tmp/hermes-timeline-preview/catalog.json

python3 scripts/serve_factory_dashboard.py \
  --board-db /Users/example/.hermes/kanban.db --board-id default \
  --hermes-home /Users/example/.hermes \
  --published-state /Users/example/.hermes/state/factory/published.json \
  --catalog /private/tmp/hermes-timeline-preview/catalog.json \
  --policy-db /private/tmp/hermes-timeline-preview/models.db --port 4611
```

Use explicit paths for your installation. Sources remain read-only. The separate policy database is the only configuration written by the dashboard. Local catalog export binds each worker profile before reading model configuration and credential-availability flags; output contains only provider/model identifiers. It uses local static choices plus the explicitly configured model, without fetching provider catalogs or making paid calls. Re-export and restart after provider/model configuration changes. Local availability cannot guarantee provider runtime acceptance.

The header deliberately says **Preview configuration**: the running gateway has not been patched or activated. Saving here does not claim that the live scheduler uses the selection. Missing data, included subscription usage and partial estimates retain the snapshot dashboard's semantics.

## Prepared dispatch integration

The integration targets inspected Hermes revision `d923a5eb487a17c0a68801bba9ef0f56c81040a8`. It comprises a generic core patch and a standalone plugin; the plugin never edits core files.

The hook `resolve_kanban_worker_model` receives keyword fields `task` (plain mapping), `workspace`, `board`, and `board_path`. It must synchronously return None for unmanaged tasks or `{provider, model, source, revision, root_id}`. More than one claiming resolver, invalid results, or resolver exceptions fail dispatch through the existing failure handling. Narrow callback signatures receive only declared fields. The selected model is stored once in `task_runs.metadata.worker_model_selection` before launch; the actual observed session model remains separate evidence.

Before activation, review the patch against your installed revision and stop dispatch through your normal service workflow. Apply the patch only to the intended checkout, run the documented tests, then build the plugin:

```sh
python3 scripts/bundle_factory_plugin.py /private/tmp/factory-models
```

Install that directory using Hermes's supported local plugin installation flow, then enable `factory-models` in `plugins.enabled` under the dispatcher-owning profile. Set these non-secret values through Hermes's configuration writer, under `plugins.entries.factory-models.settings`:

```yaml
board_path: /absolute/path/to/kanban.db
board_id: default
policy_path: /absolute/path/to/models.db
catalog_path: /absolute/path/to/catalog.json
```

Use the same database/catalog paths as the dashboard. The plugin matches both board ID and canonical database path, recognizes the existing `FACTORY:` parent and terminal `(t_<hex>)` stage convention, and validates each participating role at dispatch. Newly created stages inherit their parent's override. A conflicting native card override blocks launch with a clear error; align or clear it through existing Hermes controls. Native overrides on unmanaged tasks keep their behavior.

Restart/reload the owning dispatcher only after these changes are reviewed. Verify a disposable task's captured provenance before any production rollout. No installation or activation was performed by this implementation. Removing/disabling the plugin restores native dispatch model selection for future attempts; preserve the policy database and run metadata for rollback/audit. Reverse the core patch only after disabling the consumer and checking the installed version.

## Validation

```sh
python3 -m unittest discover -s tests/dashboard -p 'test_*.py' -v
node --check factory_dashboard/assets/live.js
node --check factory_dashboard/assets/timeline.js
```

In the isolated patched Hermes checkout, use its prescribed runner and a test interpreter:

```sh
HERMES_PYTHON=/path/to/test/python scripts/run_tests.sh \
  tests/hermes_cli/test_kanban_worker_model_resolution.py \
  tests/hermes_cli/test_kanban_db.py \
  tests/plugins/test_kanban_model_override.py \
  /absolute/path/to/dashboard/tests/hermes_integration/test_factory_model_dispatch.py
python scripts/check --base HEAD
```

The external integration test runs from the Hermes checkout so imports target that checkout, uses a temporary home and real plugin discovery, and intercepts workers before process creation. Tests make no paid model calls. See `factory-timeline-controls-results.md` for observed results and baseline failures.

## Live profile model and effort settings

Add `--profile-settings-source /Users/example/.hermes/hermes-agent` to the actual-board server command and use a Hermes Python interpreter. This enables authenticated loopback writes to the catalog-allowlisted profile config files. Click **Profile settings** to select any Factory profile, model, and reasoning effort, then **Save profile**. Model and effort are persisted together using Hermes atomic config replacement; unrelated configuration is preserved. The full-file revision rejects stale edits. Profile configuration is the source of truth. Task-wide overrides remain staged and are labeled separately.

Effort choices are Hermes settings; provider adapters may normalize them. The timeline shows effort from the linked session's recorded reasoning configuration, never today's profile default. Missing values are labeled Not recorded. Current task effort overrides are labeled as current, not historical. The running summary reflects recorded Factory attempts.

#### Scenario: Change a profile default

- **GIVEN** a Factory profile and its current configuration revision
- **WHEN** its model and effort are saved from Profile settings
- **THEN** both values are atomically written to the actual profile configuration
- **AND** future workers inherit them unless a task override applies
- **AND** existing attempts retain their recorded settings

#### Scenario: Another editor changes the profile

- **GIVEN** a profile form opened before an external configuration edit
- **WHEN** the old form is saved
- **THEN** saving is rejected and the newer configuration is preserved
