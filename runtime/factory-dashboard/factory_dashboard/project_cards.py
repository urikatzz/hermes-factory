"""Per-stage project instructions layered on the existing worker contract."""
import json
from .workflow_cards import build_stage_card

SCOPE = '''Read the request and inspect the project without modifying it. Retain PLAN.md with initial acceptance IDs.
Set metadata.project_scope to exactly {"art":boolean,"audio":boolean,"ui":boolean,"ux":boolean}.
Art/audio mean creation, modification or integration of those assets. UI/UX mean affected user-facing surfaces or journeys.
Choose from evidence; do not infer false merely because the request omitted an existing integration.'''

ARCHITECT = '''Read every inherited director plan before designing code. Retain PLAN.md and project-plan.json.
Break the work into 1..40 small tasks in project-plan.json: {"tasks":[{"id":"lowercase-id","title":"...","owner":"developer|artist|sound-designer","dependencies":["task-id"],"acceptance":{"AC1":"observable criterion"},"needs":{"art":false,"audio":false,"ui":false,"ux":false},"risk":"normal|high","preserve":["optional path or narrow glob this task must leave byte-identical"]}]}.
The JSON document top level must be exactly {"tasks":[...]} with no other keys (no plan, root or metadata keys).
Keep each task title under 120 characters; put detail in acceptance.
risk is optional (default normal). Use high only for security-sensitive, concurrency, data-migration or cross-cutting changes: those tasks get the second selected code reviewer.
If the work needs art, audio, UI or UX that PROJECT_CONTEXT scope marks false, set metadata.scope_additions to those domains, e.g. ["art"]. Added art/audio first runs the missing director, then this stage again with its plan; do not plan around a missing director.
Every PLAN.md AC must be covered by at least one task; use the same AC IDs in task acceptance.
Asset tasks precede code tasks that integrate their output: declare those dependencies explicitly.
Plans must preserve the directors' asset paths, visual/audio criteria, and code integration contracts.
The engine also runs a final integration cycle over every project AC. No code or asset writes in this stage.
An independent reviewer checks this plan before any task starts.'''

REPLAN = '''This is a revision of the earlier plan; PROJECT_CONTEXT.replan gives the reason, the failing task and its findings.
Correct the plan defect: fix wrong or untestable acceptance criteria, split oversized tasks, add missing tasks or dependencies.
Tasks in PROJECT_CONTEXT.completed_tasks already passed: keep each of them in project-plan.json exactly as captured.
Do not weaken an acceptance criterion merely so failing work passes; do not change director intent.'''

PLAN_REVIEW = '''Review the architect's PLAN.md and project-plan.json against the request, scope and inherited director plans. Read-only.
Check: every request requirement maps to an acceptance criterion; each criterion is observable and testable; tasks are small,
correctly owned and ordered; dependencies are complete; director asset paths and criteria are preserved; scope booleans are right.
Retain PLAN-REVIEW.md. Report defects in metadata.findings as "F<n>|SEVERITY|AC or -|task-id|problem and required change".
BLOCKER/HIGH (and MEDIUM tied to an AC) return the plan to the architect; use LOW/NIT for suggestions.
Classify every finding in metadata.finding_classes {"F1":"correction"|"architectural"}: correction = a localized wording, metadata or consistency defect
that can be fixed without changing any task, owner, dependency, need or acceptance criterion; architectural = anything else. When unsure, say architectural.
Use the inherited project acceptance IDs in ac_ids and finish DONE; this stage creates no plan of its own.'''

PLAN_CORRECTION = '''Targeted plan correction (not a replan). The findings below are localized wording, metadata or consistency defects of the approved plan.
Correct only what they name, in PLAN.md and in project-plan.json constraints; keep every valid part. You must NOT change any task, id, title, owner, dependency,
need, risk or acceptance criterion, add or remove tasks, or weaken anything. Integrity baselines (hashes, sizes) already in the plan stay exactly as they are,
labelled as the baseline; report corrected or current values separately, measured from disk read-only, never in place of the baseline. Re-attach PLAN.md and
project-plan.json (tasks unchanged) and finish DONE with the inherited project ac_ids.'''

PLAN_CORRECTION_REVIEW = '''Focused plan-correction review (read-only). Check ONLY (1) that each listed finding is resolved by the corrected PLAN.md and project-plan.json, and
(2) the requirements directly affected by the correction (the acceptance criteria and sections the findings name). Do not reopen unrelated parts of the plan and do
not raise new wording nits. Retain PLAN-REVIEW.md. Report in metadata.findings, as "F<n>|SEVERITY|AC or -|where|problem", only a listed finding that is still unresolved
or a defect the correction itself introduced. Set metadata.plan_defect if the correction changed the architecture or an acceptance criterion. Finish DONE with the
inherited project ac_ids.'''

PLAN_DEFECT = '''If the failure comes from a wrong, contradictory or untestable task plan or acceptance criterion rather than from the
implementation, set metadata.plan_defect to a one-sentence reason. The engine then returns the project to the architect instead of repairing.'''

PREPARE_OUTPUT = 'Create PLAN.md with numbered AC1..ACn and a Manifest include list. Attach PLAN.md; do not modify PROJECT_DIR.'

DIRECTOR = '''Read the request and inherited scope. Retain PLAN.md with observable director criteria, target asset paths,
style bible references, integration constraints, and how the final result will be compared.
Art: include visual references and specify intended in-engine appearance. Every asset class needs at least one reference image in the style bible: review scores each render against it and blocks below 80% similarity. Audio: specify audible intent and listening examples.
Read any existing bible without changing its approved rules. If the required bible is absent, propose a style-bible creation task
before asset production, with validation criteria, class limits, and references; do not require a separate preexisting project.
Do not approve the assets or implement them in this planning stage.
A human must approve the art director's plan before architecture starts. If PROJECT_CONTEXT.human_feedback is present,
a human rejected the previous plan: revise it to address that feedback.'''

TOOL_INCIDENTS = '''Tool incidents: when the safety guard refuses a command or a tool is missing, first use an approved alternative that gives the same
evidence (file tools, a script file, a narrower command). Record every refusal, resolved or not, in metadata tool_incidents:
[{command, reason (safety_guard|missing|timeout|other), required (true if an acceptance criterion needs it), resolved (true only if the
alternative produced the evidence), alternative (what worked, else ""), affected_criteria ([AC ids])}]. Only an unresolved required tool
is blocked work: also list it in blocked_tools and mark the affected criteria unverified:environment. A resolved or optional incident never is.'''

SPEC_CONSTRAINTS = '''Approved constraints: PROJECT_CONTEXT.constraints lists the requirements the plan and the human fixed, each with an id and a kind
(immutable paths, palette, layout, architecture, behavior, acceptance). Respect all of them. Before you implement a repair, check that it
does not violate any constraint. If satisfying a finding would, do not implement it: finish VERDICT=BLOCKED with blocked_reason naming the
constraint and metadata spec_conflicts [{"constraint":"c_xxxxxxxx","reason":"...","finding":"profile:F1"}]. If a finding you raise can only be
fixed by violating a constraint, still report it, and add the same spec_conflicts entry so a human decides instead of the repair budget being spent.'''

CONFLICT_CHECK = '''Specification conflict check (read-only; no code, no project changes). The findings below block this task. For each finding decide whether
every way of fixing it would violate one of the listed approved constraints. Report only genuine contradictions: a finding that can be fixed
within the constraints is NOT a conflict. Retain a short report.md. Complete with verdict NO_BLOCKING_FINDINGS and no findings. Put each genuine
contradiction in metadata spec_conflicts [{"constraint":"<id from the list>","reason":"why the fix must violate it","finding":"<finding text start>"}],
or an empty list. Use only constraint ids from the list.'''

COMPARISON = '''Compare the actual result against the inherited director plan, in addition to lint and normal review.
For art tasks retain rendered asset images; for final integration retain actual in-engine screenshots.
If perception is unavailable, record it as an unresolved required tool incident (blocked_tools and unverified:environment) in the retained report; do not approve.
Retain comparison.json with exactly: schema="factory-comparison/v1", plan_sha256=<director PLAN hash>,
manifest_sha12=<reviewed manifest>, mode="rendered_asset" (art task) or "rendered_in_engine" (final art),
source="tool"|"human", outcome="pass"|"fail", criteria=[{rule,expected,observed,outcome:"pass"|"fail"}],
evidence=[absolute retained image paths]. Include the comparison file and all cited evidence as completion artifacts.
For a mismatch report actionable findings with the relevant task AC and CHANGES_REQUIRED so the engine invokes the artist.
An unclear or contradictory director plan requires human review; never silently redefine intent.'''

SIMILARITY = '''Before any detailed judgement run the art-review similarity gate: the Jev model scores each rendered asset against its
reference images. Retain similarity.json as a completion artifact. If any asset scores below 80% or has no reference image, stop there:
report those scores as blocking findings with CHANGES_REQUIRED and skip comparison.json. Only when every asset reaches 80% do the
detailed comparison to find what is still missing. If the model is unavailable record an unresolved required tool incident (blocked_tools); never estimate the score yourself.'''

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
    if project.get('replan'):
        details['replan'] = project['replan']
    if project.get('approvals'):
        details['human_approvals'] = project['approvals']
    if stage.profile in project.get('director_feedback', {}):
        details['human_feedback'] = project['director_feedback'][stage.profile]
    if task and project.get('work', {}).get('attribution'):
        details['repair_attribution'] = project['work']['attribution']
    if project.get('recovery_note'):
        details['human_recovery_note'] = project['recovery_note']
    if task:
        from .project_decisions import constraints_of
        shown = constraints_of(project)
        if shown:
            details['constraints'] = [{k: c[k] for k in ('id', 'kind', 'reason', 'preserve', 'paths', 'colors', 'rules', 'acs') if c.get(k)} for c in shown]
    if project.get('handoff_rejections', {}).get(stage.key):
        details['previous_handoff_rejected'] = project['handoff_rejections'][stage.key]
    if project.get('waivers'):
        # Reviewers keep reporting the true result; the gate applies the human's scoped waiver and keeps the original finding.
        details['human_waivers'] = [{k: w[k] for k in ('id', 'ac', 'path', 'source', 'reason')} for w in project['waivers']]
    if project.get('constraints'):
        details['human_constraints'] = [{k: c[k] for k in ('preserve', 'reason')} for c in project['constraints']]
    text = '\nPROJECT_WORKFLOW_VERSION 2\nPROJECT_CONTEXT ' + json.dumps(details, sort_keys=True)
    if task:
        text += '\nOnly the TASK acceptance IDs apply to this cycle. Inherit the directors\' plans and architecture; do not substitute current defaults.'
        text += '\nPreserve outputs of completed tasks. Keep the cumulative manifest so the final integration snapshot includes the whole project.'
        card['title'] = task['title'] + ' · ' + card['title']
    if stage.key == 'project-plan-review':
        card['body'] = card['body'].replace(PREPARE_OUTPUT, 'Create PLAN-REVIEW.md; do not modify PROJECT_DIR.')
    if stage.profile == 'factory-retro':
        card['body'] = card['body'].replace(PREPARE_OUTPUT, 'Create RETRO.md; do not modify PROJECT_DIR.')
        text += '\nPROJECT_HISTORY ' + json.dumps(project.get('history', []), sort_keys=True)
        if not project.get('ac_ids'):
            text += '\nNo project ACs were captured before failure. Use retrospective-only AC1: retain an evidence-backed RETRO.md; this cannot establish product acceptance.'
    card['body'] += text
    if stage.profile == 'factory-retro':
        card['skills'].append('factory-retro')
    if stage.profile in ('artist', 'sound-designer'):
        card['skills'].append('art-production' if stage.profile == 'artist' else 'audio-production')
    if stage.profile == 'art-reviewer':
        card['skills'].append('art-review')
    return card
