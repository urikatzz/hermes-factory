# Project workflow v2 implementation and installation

Validated on 2026-11-14. No model calls or production task submissions were made for validation.

## Installed behavior

- Scope classification → relevant directors → architect → captured small-task dependency graph.
- Independent task cycles with cumulative manifests and dependency ordering; shared-directory writers run serially.
- Verification is required before reviewer cards exist. Changed implementations repeat verification and all selected reviews.
- Code/security and relevant UX/UI/art/audio review; specialist asset repairs and bounded cycles.
- Retained director/manifest-bound perceptual comparisons. Missing tools block rather than establish approval.
- Final integration over all project acceptance criteria, followed by a read-only Factory retrospective.
- Explicit human recovery creates fresh verification/review attempts. Terminal outcomes retire sibling review attempts.

The repository owns the runtime under `runtime/factory-dashboard`, plus the retro skill and installer. Installation updates the main dashboard source and every existing profile-local policy consumer, and registers the retro profile, worker skill, catalog entry and captured model setting.

## Verification evidence

| Check | Result |
| --- | --- |
| New `tests/workflow_v2` suite, using Hermes Python with PyYAML | 29 passed |
| Archived v1 compatibility modules: capture, cards, gate, templates, readiness, reports and UI | 31 passed |
| Real disposable Hermes board, synthetic stage handoffs | Scope, architecture, full task cycle, final integration and retro completed; 11 stages, zero model calls |
| JavaScript syntax and Git whitespace checks | Passed |
| SVG XML, README links and diagram visual inspection | Passed |
| Installed-release preview | Zero file differences from the repository-owned release |
| Existing immutable task snapshots | All 3 pre-install snapshots retained byte-for-byte |
| Live `/api/workflows` | Enabled; all required enforcement hooks ready; retro registered |

Feature, Bug fix and Chore advanced from revision 2 to revision 3. Game Art and Game Audio advanced from revision 1 to revision 2. All five active heads capture `execution_version: 2`; historical revisions and snapshots remain intact.

The ECC suite additionally ran against the original installed source before activation: 29 passed and 4 failed because older tests expect three presets rather than the five already present. An archived HTTP test has the same stale three-template expectation, reproduced against the unmodified installed source. These existing test assumptions were not changed as part of this work.

## Runtime and backups

Private replacement-file and settings backups are under:

- `~/.hermes/backups/project-workflows-v2-20261114`
- `~/.hermes/backups/project-workflows-v2-20261114-final`
- `~/.hermes/backups/project-workflows-v2-20261114-verified`

Each includes a preparation manifest and an applied receipt. Later passes synchronized final tested refinements without adding more template revisions. They did not restore or rewrite historical databases.

The dashboard was restarted on port 4610. The gateway was restarted to load the policy code. macOS initially rejected supervision because `ai.hermes.gateway` was disabled; the existing launch agent was re-enabled and confirmed running under launchd.

## Limits

The installed audio-reviewer still lacks a capable listening tool. It requires genuine retained human listening evidence or a subsequently configured listening capability; measurements alone cannot pass perceptual review. No listening capability or subjective assessment was fabricated.

The tests establish controller policy, persistence, guards, retention/linkage and installation behavior. They do not establish actual game appearance or sound quality, model performance, or the authenticity of subjective worker/operator observations. Rendering and listening must occur during real project reviews.

No Git commit or push was made for this implementation.
