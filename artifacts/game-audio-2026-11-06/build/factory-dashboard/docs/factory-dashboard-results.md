# Dashboard validation results

Implementation workspace: `/private/tmp/hermes-factory-dashboard`, branch `feat/factory-dashboard`. No commits, pushes, installed Hermes changes, model calls or Docker operations were made for this dashboard.

## Initial checks before final review

- 28 focused Python checks pass: 8 collector, 11 aggregation, 4 renderer and 5 CLI cases. Every task began with failing checks for its missing behavior, followed by passing checks.
- `node --check factory_dashboard/assets/report.js` passes.
- Private pilot report generated with 0 warnings: 2 unlinked tasks, both explicit worker sessions, 28,723 input tokens, 1,254 output tokens, 181,248 cache-read tokens, 206 reasoning tokens. Both sessions are Included; actual USD unavailable. Both manifests match `9b734edbedb2`; both sandbox records finalized cleanup as removed.
- Read-only live report generated with 0 collection warnings: 7 parents, 25 unlinked tasks, 174 recorded attempts and 88 linked worker sessions. 86 attempts lack usage links. Known recorded estimates total approximately $135.01 from 48 sessions; 40 sessions are marked Included. No actual USD amounts are recorded. This estimate is partial, not total Factory spending.
- Synthetic report generated with 3 parents, shared-session attribution, a failed-verdict/done stage, included usage and hostile script-closing task text.

## Browser inspection blocked

The available computer-use tool reports no browsers, no native applications, and `Sky Computer Use native pipe startup failed`. Opening a Chrome tab also reports browser unavailable. No alternate browser automation technology was used to bypass that tool boundary. Visual layout at desktop/narrow widths, keyboard navigation, filter interaction and browser network behavior remain unverified. Static rendering checks and JavaScript syntax checks do not establish those behaviors.

## Scope

Live source access used the selected board and explicitly linked profile-session databases in SQLite read-only transactions. The report includes source timestamps and acknowledges the absence of a globally atomic cross-database snapshot. No inferred joins or price lookups were used. Final review findings and any fixes will be appended below.

## Final review and fixes

A fresh reviewer inspected the immutable SHA256 source manifest and reported no Critical findings, five Important findings, and two additional presentation/sorting issues. The author fixed the material issues in one pass:

- Physical database identity now scopes session deduplication, preventing case aliases or hardlinks from counting a session twice.
- Terminal attempts/tasks with missing end timestamps retain unknown durations; only ongoing records use snapshot time.
- Current blockers are shown only for blocked tasks; old failures remain in recorded attempts/events.
- Strict JSON decoding rejects nonfinite constants and numeric overflow inside optional-record boundaries, producing warnings instead of aborting rendering.
- Per-task cost presentation shows actual, estimated, included and unknown categories separately with session coverage. Pure presentation functions run in Node checks.
- Stage sort tuples use consistent types, including unknown labels and large cycle numbers. Parent overview rows now include blocker, usage/cost coverage and delivery state; summary includes root-status counts, active attempts and failed verdicts without attempts.

All 39 focused checks pass after these fixes, including regressions observed failing first. Individual JavaScript asset syntax checks pass. Live, private-pilot and synthetic reports were regenerated successfully with 0 collection warnings. Live counts and partial estimated spending remain as described above. The deliverable copies are `/Users/example/orca/projects/hermes/reports/factory-live.html` and `factory-pilot.html`, both mode0600.

### Rulings and verification limits

- Explicitly selected source roots are normalized to accommodate macOS `/var` and `/tmp` aliases; selected file/profile descendants still reject symlinks.
- Root attempts participate in parent usage; execution-retry metrics follow the approved child-stage definition.
- Because commits are not authorized, the review used an immutable source/hash manifest rather than an empty Git commit range.
- The reviewer classified the large-cycle sorting issue as Minor; it was treated as material because valid task titles could abort generation. Missing approved overview fields were completed in the same pass.
- Browser behavior remains unverified due the concrete tool failure above; static checks do not establish responsive layout, focus/filter behavior, or actual browser network behavior.
- Review did not independently reread live/pilot source contents. Author generation/record checks confirmed successful read-only source collection, explicit links, pilot manifests/cleanup and preservation of missing-cost labels; no independent billing reconciliation is claimed.

No review findings were intentionally deferred. No live activation or Git integration was performed. Source remains uncommitted in the isolated feature worktree.
