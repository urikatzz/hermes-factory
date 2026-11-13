# Project workflows v2

Version 2 introduces project planning above small, dependent task cycles. `execution_version: 2` is captured in immutable workflow revisions. Definitions without the field remain version 1 and continue through the original controller, including its original review/verification sequencing.

## Project planning

1. `factory-orchestrator` inspects the request/project read-only, retains `PLAN.md`, and records `project_scope` with `art`, `audio`, `ui`, and `ux` booleans.
2. Relevant `art-director` and `audio-director` stages retain their plans. The current implementation schedules them serially. With no art or audio, it goes directly to architecture.
3. `architect` receives all those retained plans and writes the project architecture, acceptance criteria and `project-plan.json`.

The JSON contains `tasks`, each with `id`, `title`, `owner`, `dependencies`, `acceptance`, and `needs`. Owners are `developer`, `artist`, or `sound-designer`; `needs` uses the four scope booleans. Every project AC must be covered. IDs are unique, dependency references must exist, and cycles are refused. Code tasks integrating art/audio must depend on the corresponding asset-production tasks. There are at most 40 small tasks per project.

```json
{
  "tasks": [
    {
      "id": "sprites",
      "title": "Create the player sprite",
      "owner": "artist",
      "dependencies": [],
      "acceptance": {"AC1": "Player sprite matches the director plan"},
      "needs": {"art": true, "audio": false, "ui": false, "ux": false}
    },
    {
      "id": "integrate",
      "title": "Integrate the sprite into gameplay",
      "owner": "developer",
      "dependencies": ["sprites"],
      "acceptance": {"AC2": "Player renders and moves correctly"},
      "needs": {"art": true, "audio": false, "ui": false, "ux": true}
    }
  ]
}
```

## Task execution and repairs

Dependency-ready tasks run serially because they write into one shared project directory. Every task inherits the captured director and architecture plans, dependencies, acceptance criteria and model snapshot. Each task has separate stage keys, worker attempts, gate events and a bounded repair count; these live under the project root rather than creating independent untracked root cards.

The sequence is writer → verifier → selected review panel. Verification must explicitly PASS with complete acceptance coverage, a matching manifest, successful release audit, and no failed checks or unavailable tools. No reviewer cards are materialized before this gate passes. Unlike the legacy policy, v2 does not waive an unavailable Unity environment into a verifier pass.

Code review and security review are required. The captured template selects Claude/Codex code reviewers; UX and UI reviewers run when the task declares those needs. Art/audio reviewers run for relevant tasks.

Blocking findings route to the owning specialist: art-reviewer → artist, audio-reviewer → sound-designer, and code/security/UX/UI findings → fixer. The verifier can declare `repair_domains: ["code", "art", "audio"]` to identify asset failures. Mixed repairs run serially and finish with a cumulative implementation manifest. Every repair restarts verification and then the complete selected review panel; earlier approvals cannot approve a changed manifest.

The captured template's repair limit applies to each task and final integration separately. Exhausted limits and evidence contradictions require human review. Missing tools/environment block the workflow. After explicit recovery, `resume_factory_workflow.py` requires a human note and creates fresh verification/review evidence without consuming an implementation repair cycle. It cannot waive a defect or change scope.

## Comparing director intent to the result

Asset lint remains required, but it cannot establish perceptual approval. Specialist reviewers retain `comparison.json`, bound to the director PLAN's SHA256 and the reviewed implementation manifest, with expected/observed criteria, outcomes and retained evidence paths.

- Art tasks require rendered asset images (`rendered_asset`); final integration requires actual in-engine images (`rendered_in_engine`).
- Audio requires `listened` evidence from an available capable tool or a retained human listening evaluation. Waveform images, spectra, loudness and transcription alone are insufficient. The currently installed reviewer has no listening tool; it must report the capability gap rather than fabricate an observation.
- A director mismatch requires a blocking finding and `CHANGES_REQUIRED`, which routes repair to the asset producer. Conflicting or insufficient plans require human review, not a silent change to intended style or sound.

Evidence is operator/worker-retained reporting, not an independent authentication system. A claim of human listening must actually come from a human evaluation; the controller validates identity, shape, retention and linkage, not the truth of a subjective observation.

## Integration and retrospective

After all tasks pass, the developer assembles the project and a final verifier-first cycle checks every project AC and the integrated visual/audio result. Only this cycle's manifest/snapshot can become the delivered project.

`factory-retro` runs after a successful or unsuccessful project outcome. It writes retained `RETRO.md` with evidence, root causes, prioritized improvements, tradeoffs and validation steps. It has a scratch workspace and cannot apply improvements, modify Factory configuration, change outcomes, or publish. A missing retro report cannot silently become success.

## Installation

Use the Hermes Python environment (Python 3.11+ with PyYAML):

```sh
python scripts/install_project_workflows.py --home /path/to/.hermes \
  --preview /tmp/project-workflows-preview.json
python scripts/install_project_workflows.py --home /path/to/.hermes \
  --apply-preview /tmp/project-workflows-preview.json \
  --backup-dir /path/to/new/private/project-workflows-backup
```

The preview contains hashes and affected paths, not credentials. Apply checks it is still current, backs up replaced files and the settings database privately, installs the runtime and profile-local policy bundles, adds the retro profile/skill/model setting, and creates new active template revisions. It preserves old template revisions and task snapshots. A partial filesystem install retains `prepared.json` and its backups; `applied.json` is written only after template activation succeeds.

Restart long-running gateway/dashboard consumers after installation so their imported policy code matches the installed source. Do not remove the v2 runtime while captured v2 projects exist. To return future submissions to v1, save new template revisions with `execution_version: 1`; do not restore an old database over current snapshots. Consistent board/settings backups are required for disaster recovery.

## Verification

```sh
python -m unittest discover -s tests/workflow_v2 -p 'test_*.py' -v
python tests/workflow_v2/native_smoke.py
node --check runtime/factory-dashboard/factory_dashboard/assets/workflow_forms.js
```

The native smoke check needs the local Hermes source/environment. It creates a disposable board and uses synthetic handoffs; it does not call a model, run a paid task or enqueue anything on the production board.
