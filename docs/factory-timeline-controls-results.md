> Superseded by [Factory task snapshots results](factory-task-snapshots-results.md): timelines are read-only and defaults now apply only to new tasks.

# Timeline implementation verification

Implementation: `/private/tmp/hermes-factory-dashboard`, existing isolated `feat/factory-dashboard` worktree. Integration: `/private/tmp/hermes-timeline-integration`, branch `feat/factory-model-resolution`, baseline `d923a5eb487a17c0a68801bba9ef0f56c81040a8`. No commits, pushes, installed Hermes edits, or scheduler activation.

## Automated evidence before final review

- Existing dashboard baseline: 39 passing checks.
- Current dashboard: 63 passing checks, including provider/model precedence, board isolation, immutable revision snapshots, concurrent edits, persistence, cross-role compatibility, offline catalog export, dispatch consumer behavior, HTTP controls, save failure semantics and timeline interval derivation. Duplicate inherited tests were removed from the final count.
- New Hermes resolver tests: 4 passing.
- Existing native model-override tests: 16 passing.
- Actual plugin discovery and dispatch integration: 1 passing. The test builds the self-contained plugin, uses a temporary home/board/catalog/policy, observes model selection before intercepted worker launch, resets the parent override, and confirms later stages inherit role defaults while earlier captured metadata remains unchanged.
- Broader Hermes dispatch suite: 53 pass, 1 fail, 1 platform skip. Overall combined run: 74 pass, 1 fail, 1 skip. The failing `test_infrastructure_spawn_refusal_never_charges_the_card` also fails on untouched baseline d923a5e on macOS. Its systemd-scope assumption does not hold on this host. It was not altered or suppressed.
- Hermes `scripts/check --base HEAD`: all 12 checks pass using pinned Ruff 0.15.10 in a separate disposable lint environment.
- Modified JavaScript syntax checks pass. Existing standalone snapshot CLI remains available and is exercised by the dashboard suite.

## Browser evidence

Chrome inspection was available for this task. Desktop and 390×844 layouts were inspected. Task-wide override changed all three demonstration lanes to the selected model; reset restored planner/reviewer and builder defaults independently. Editing the builder default changed only its future selection. Historical bars retained their originally recorded models. Attempt selection opened timing, outcome, model and cost details.

Search focus loss across automatic refresh was reproduced and corrected; subsequent read-only DOM inspection showed focus and query retained. A render error introduced during a lane-layout edit was caught in the browser and corrected before delivery. A completed root without run history now appears as missing history, not queued work. Unknown-duration attempts remain inspectable without a fabricated duration bar.

The source-failure and conflict responses are covered at the HTTP/service level. Full provider execution, production gateway reload, plugin host-process isolation mode and the remote Windows/Linux runners were not exercised. The integration test stops before process creation and makes no model calls.

## Actual board preview

A local catalog was exported from the six selected Factory profiles without credentials or remote model calls. The live read-only collector returned seven parent tasks with zero collection warnings. This verifies collection, not billing completeness. Model configuration is stored only in a separate `/private/tmp/hermes-timeline-preview/models.db`; the installed scheduler does not consume it until the reviewed integration is activated.

- Demonstration: http://127.0.0.1:4610
- Actual board with staged controls: http://127.0.0.1:4611

## Implementation rulings

- Uncommitted work is preserved and reviewed with SHA256 inventories; no commit-based rollback is claimed. The original dashboard is backed up at `/private/tmp/hermes-dashboard-before-timeline.tgz`.
- Core metadata uses the generic `worker_model_selection` name and plain-mapping hook payload, with explicit board path. Factory-specific inheritance remains in the plugin.
- Catalog refresh uses a credential-free local export. This avoids provider calls during polling, at the cost of re-exporting/restarting after model availability changes.
- The existing private spawn-call helper moved into a sibling module to respect Hermes's file-size ratchet. No external references to that helper were found.
- A bundle script copies the five required standard-library modules into the standalone plugin. Rebuild it when their source changes; production does not rely on a development PYTHONPATH.

## Independent final review

The independent review could not run: its agent failed with a workspace credit-limit error. Author review was completed instead; this is not independent approval.

Author review found and fixed plugin configuration loading before unmanaged-task classification. A regression failed before the fix and passes afterward. Ordinary tasks no longer require Factory policy/catalog configuration. It also corrected indefinite visual-refresh deferral after selecting an attempt: buttons retain focus by stable identity across refresh; active form inputs defer rendering with an explicit paused indicator.

Final dashboard run: 63 passed. Final isolated dispatch run: 74 passed, 1 pre-existing baseline failure, 1 skipped. Live activation remains outside this delivered implementation.

## Live effort settings verification

67 dashboard tests pass, including authenticated profile writes, stale revision conflicts, unknown profiles/efforts, preservation of unrelated config, and session-only effort reporting. The actual Hermes atomic writer passed a disposable-config round trip. Browser save of Architect's unchanged Opus 5.5/high settings succeeded; all ten API profile values matched actual files afterward. No workers were launched. All ten profiles remain high. Profile model/effort settings are now live; the prior preview-only limitation applies only to task-wide overrides. No commits or pushes.
