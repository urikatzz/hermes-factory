"""Per-stage project instructions layered on the existing worker contract."""
import json
from .workflow_cards import build_stage_card

SCOPE = '''Read the request and inspect the project without modifying it. Retain PLAN.md with initial acceptance IDs.
Set metadata.project_scope to exactly {"art":boolean,"audio":boolean,"ui":boolean,"ux":boolean}.
Art/audio mean creation, modification or integration of those assets. UI/UX mean affected user-facing surfaces or journeys.
Choose from evidence; do not infer false merely because the request omitted an existing integration.'''

ARCHITECT = '''Read every inherited director plan before designing code. Retain PLAN.md and project-plan.json.
Break the work into 1..40 small tasks in project-plan.json: {"tasks":[{"id":"lowercase-id","title":"...","owner":"developer|artist|sound-designer","dependencies":["task-id"],"acceptance":{"AC1":"observable criterion"},"needs":{"art":false,"audio":false,"ui":false,"ux":false}}]}.
Every PLAN.md AC must be covered by at least one task; use the same AC IDs in task acceptance.
Asset tasks precede code tasks that integrate their output: declare those dependencies explicitly.
Plans must preserve the directors' asset paths, visual/audio criteria, and code integration contracts.
The engine also runs a final integration cycle over every project AC. No code or asset writes in this stage.'''

DIRECTOR = '''Read the request and inherited scope. Retain PLAN.md with observable director criteria, target asset paths,
style bible references, integration constraints, and how the final rendered/listened result will be compared.
Art: include visual references and specify intended in-engine appearance. Audio: specify audible intent and listening examples.
Read any existing bible without changing its approved rules. If the required bible is absent, propose a style-bible creation task
before asset production, with validation criteria, class limits, and references; do not require a separate preexisting project.
Do not approve the assets or implement them in this planning stage.'''

COMPARISON = '''Compare the actual result against the inherited director plan, in addition to lint and normal review.
For art tasks retain rendered asset images; for final integration retain actual in-engine screenshots.
For sound use actual listening through an available capable tool or retain a human listening evaluation.
Waveforms, spectra, loudness and transcription alone are NOT listening evidence. Never claim you listened if you cannot.
If perception is unavailable, report blocked_tools and unverified:environment in the retained report; do not approve.
Retain comparison.json with exactly: schema="factory-comparison/v1", plan_sha256=<director PLAN hash>,
manifest_sha12=<reviewed manifest>, mode="rendered_asset" (art task), "rendered_in_engine" (final art), or "listened" (audio),
source="tool"|"human", outcome="pass"|"fail", criteria=[{rule,expected,observed,outcome:"pass"|"fail"}],
evidence=[absolute retained image/listening evaluation paths]. Include the comparison file and all cited evidence as completion artifacts.
For a mismatch report actionable findings with the relevant task AC and CHANGES_REQUIRED so the engine invokes the artist or sound-designer.
An unclear or contradictory director plan requires human review; never silently redefine intent.'''

RETRO = '''Analyze the retained project/task history: verification failures, review findings, repair cycles, missing tools,
stage outcomes and final integration. Retain RETRO.md with evidence references, root causes, and prioritized Factory improvements.
Separate project defects from reusable improvements to Factory prompts, tooling, checks and workflow policy.
For every proposal give the observed problem, evidence, proposed change, expected benefit and how to validate it.
Work read-only in scratch. Do not change Factory settings, prompts, profiles, code, or templates; do not publish.
This is retrospective reporting, not PLAN preparation: retain RETRO.md, not a replacement project plan.
Use inherited project acceptance IDs in ac_ids and finish DONE, or BLOCKED with the exact missing capability.'''


def project_card(definition, stage, cycle, context, inputs, project, task=None):
    card = build_stage_card(definition, stage.key, cycle, context, inputs, stage_spec=stage)
    details = dict(scope=project.get('scope'), director_and_architecture_plans=project.get('plans', []),
                   task=task, project_ac_ids=project.get('ac_ids', []),
                   completed_tasks=project.get('completed', []), terminal=project.get('terminal'))
    if project.get('recovery_note'):
        details['human_recovery_note'] = project['recovery_note']
    text = '\nPROJECT_WORKFLOW_VERSION 2\nPROJECT_CONTEXT ' + json.dumps(details, sort_keys=True)
    if task:
        text += '\nOnly the TASK acceptance IDs apply to this cycle. Inherit the directors\' plans and architecture; do not substitute current defaults.'
        text += '\nPreserve outputs of completed tasks. Keep the cumulative manifest so the final integration snapshot includes the whole project.'
        card['title'] = task['title'] + ' · ' + card['title']
    if stage.profile == 'factory-retro':
        card['body'] = card['body'].replace('Create PLAN.md with numbered AC1..ACn and a Manifest include list. Attach PLAN.md; do not modify PROJECT_DIR.', 'Create RETRO.md; do not modify PROJECT_DIR.')
        text += '\nPROJECT_HISTORY ' + json.dumps(project.get('history', []), sort_keys=True)
        if not project.get('ac_ids'):
            text += '\nNo project ACs were captured before failure. Use retrospective-only AC1: retain an evidence-backed RETRO.md; this cannot establish product acceptance.'
    card['body'] += text
    if stage.profile == 'factory-retro':
        card['skills'].append('factory-retro')
    if stage.profile in ('artist', 'sound-designer'):
        card['skills'].append('art-production' if stage.profile == 'artist' else 'audio-production')
    if stage.profile in ('art-reviewer', 'audio-reviewer'):
        card['skills'].append('art-review' if stage.profile == 'art-reviewer' else 'audio-review')
    return card
