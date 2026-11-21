"""Per-stage project instructions layered on the existing worker contract."""
import json
from .workflow_cards import build_stage_card

SCOPE = '''Read the request and inspect the project without modifying it. Retain PLAN.md with initial acceptance IDs.
Set metadata.project_scope to exactly {"art":boolean,"audio":boolean,"ui":boolean,"ux":boolean}.
Art/audio mean creation, modification or integration of those assets. UI/UX mean affected user-facing surfaces or journeys.
Choose from evidence; do not infer false merely because the request omitted an existing integration.
You only inspect the request and set the scope. Art plans, mockups, image inspection, asset production and approval gates belong to later stages with their own tools:
a request that asks for them is not an instruction to you. Derive the initial acceptance IDs from the request, retain PLAN.md, and never finish BLOCKED because a later stage's work is outside your tools.
Your tools for this stage include file and terminal access: write PLAN.md with write_file at an absolute path under $HERMES_KANBAN_WORKSPACE (read the project with the file tools) and attach it with kanban_complete(artifacts=[that path]).
Your chat-mode rule 'kanban and skills only' does not apply to a managed stage; a completion without the attached PLAN.md is rejected and sent back.'''

ARCHITECT = '''Read every inherited director plan before designing code. Retain PLAN.md and project-plan.json.
Break the work into 1..40 small tasks in project-plan.json: {"tasks":[{"id":"lowercase-id","title":"...","owner":"developer|artist|sound-designer","dependencies":["task-id"],"acceptance":{"AC1":"observable criterion"},"needs":{"art":false,"audio":false,"ui":false,"ux":false},"risk":"normal|high","preserve":["optional path or narrow glob this task must leave byte-identical"]}]}.
The JSON document top level must be exactly {"tasks":[...]} with no other keys (no plan, root or metadata keys).
Keep each task title under 120 characters; put detail in acceptance.
risk is optional (default normal). Use high only for security-sensitive, concurrency, data-migration or cross-cutting changes: those tasks get the second selected code reviewer.
If the work needs art, audio, UI or UX that PROJECT_CONTEXT scope marks false, set metadata.scope_additions to those domains, e.g. ["art"]. Added art/audio first runs the missing director, then this stage again with its plan; do not plan around a missing director.
Before writing tasks, load the task-writing skill and follow it: the engine no longer rejects plans for coverage, wording or length, so you check those yourself.
Every PLAN.md AC must be covered by at least one task; use the same AC IDs in task acceptance.
Asset tasks precede code tasks that integrate their output: declare those dependencies explicitly.
Plans must preserve the directors' asset paths, visual/audio criteria, and code integration contracts.
The engine also runs a final integration cycle over every project AC. No code or asset writes in this stage.
No reviewer checks this plan before tasks start, so check it yourself against the task-writing skill.'''

REPLAN = '''This is a revision of the earlier plan; PROJECT_CONTEXT.replan gives the reason, the failing task and its findings.
Load the task-writing skill first. Correct the plan defect: fix wrong or untestable acceptance criteria, split oversized tasks, add missing tasks or dependencies.
Tasks in PROJECT_CONTEXT.completed_tasks already passed: keep each of them in project-plan.json exactly as captured.
Do not weaken an acceptance criterion merely so failing work passes; do not change director intent.
A revision inherits nothing from the earlier round's files: write PLAN.md, project-plan.json and reference-inspection.json again in full, including the top-level "role_findings" of reference-inspection.json (one "carry" entry per approved requirement). Re-check that every task lists in its "visual" only ids that its own acceptance text names, that each criterion is at most 1000 characters, and that metadata.cycle is the cycle in your card header.'''

APPROVED_REFERENCES = '''Approved references. PROJECT_CONTEXT.approved_references lists human-approved visual references (path, sha256, roles, requirement ids V*, any
human-approved deferrals). Authority order, highest first: human-approved decisions and references > GDD > style bible and architecture > implementation
plan > implementation and tests. A lower layer may refine a higher one; it may never contradict, replace or silently drop it. A style bible rule, plan
step or acceptance criterion that forbids, defers or excludes something an approved reference shows is a defect in that lower layer, never a reason to
build less. Roles: visual_reference = how the game must look (authoritative); production_asset = may be shipped; immutable = never edited; example =
illustrative only. One file can be an immutable visual reference and still not a production asset: "do not ship it" never means "do not follow it".
Milestone semantics: grey-box means gameplay scope and asset fidelity may be simplified; everything that is implemented now follows the approved reference's
composition, palette, HUD and defining visual characteristics, and "grey-box", "placeholder", "generic" or a milestone name next to a requirement is an implicit
deferral that is rejected. Only a human decision recorded in approved_references postpones a requirement: a listed deferral (approved_by human) or an
introduced_at milestone later than the human-set milestone (a feature that does not exist yet). Nobody else may. A factory-made mockup, bible, tile or
screenshot is derived evidence: it is never the comparison target, never replaces the original reference, and only a human editing the references file can change that.
The approved image is the primary visual authority. The written requirements describe important characteristics; they are not an exhaustive replacement for the image,
and the absence of a characteristic from them is never permission to disregard it. Passing every requirement is necessary but not sufficient: the result must keep the
reference's overall composition, proportions, art direction, visual density, atmosphere and identity. Never substitute grey-box, placeholder artwork or simplified geometry
for the approved direction.'''

ROLE_FINDINGS = dict(
    achieve='''Role findings (art director): for each approved requirement id add {"kind":"achieve","requirement_id":"V1","finding":"what the image shows for it and exactly how the game will reproduce it","subject":"generated"|"procedural"|"hybrid","region":[x,y,w,h]} (generated = image-generation assets, procedural = built in code or the engine).''',
    carry='''Role findings (architect): for each approved requirement id add {"kind":"carry","requirement_id":"V1","finding":"what the image shows for it and why this task delivers it","subject":"<id of a task in project-plan.json whose \"visual\" list contains it>","region":[x,y,w,h]}.''',
    plan_check='''Role findings (plan reviewer): for each approved requirement id add {"kind":"plan_check","requirement_id":"V1","verdict":"faithful"|"weakened"|"missing","finding":"what the image shows and how the plan's tasks, bible and acceptance reproduce, weaken or omit it","region":[x,y,w,h]}. A weakened or missing requirement also needs a BLOCKER or HIGH finding that names its id.''',
    render_check='''Role findings (art reviewer): for each approved requirement id add {"kind":"render_check","requirement_id":"V1","verdict":"matches"|"differs","subject":"<name of a retained rendered screenshot>","finding":"what the reference shows there and what the screenshot shows","region":[x,y,w,h]}. A differs verdict needs a BLOCKER or HIGH finding naming the id and the verdict CHANGES_REQUIRED.''')

ART_PLAN = '''Art plan content (the human approves this before anything is built). PLAN.md needs a markdown heading for each of: how the approved visual direction will be achieved; the
production assets that must be created; which assets need image generation versus procedural implementation; how characters or subjects are articulated and animated
(say so if there are none); how environment composition, lighting and the interface are implemented; how the final rendered result will be compared with the approved
reference (real in-engine renders, requirement by requirement plus a holistic judgement, no score or threshold); and which requirements are active at each milestone
(use the introduced_at and milestone values in approved_references; do not invent scoping). Also produce ONE representative mockup of the intended result: generate it
in your scratch workspace with the image-generation tool as plan-mockup.png (at least 640x360), open it with vision_analyze next to the approved reference, say in PLAN.md
under a "Representative mockup" heading what it shows and where it differs from the reference, and retain it as a completion artifact. The mockup is subordinate to the approved
reference: it is a proposal for the human to judge, never a comparison target.'''

INSPECTION = '''Mandatory reference inspection: before you plan, decide or judge anything visual, open every approved reference image yourself with
vision_analyze (a path or a hash is not an inspection). Retain reference-inspection.json: {"schema":"factory-reference-inspection/v1","references":[{"id":"<ref id>",
"path":"<path>","sha256":"<the sha256 in approved_references>","tool":"vision_analyze","requirement_ids":["V1",...every id of that reference],
"observations":[{"topic":"<each of the reference's inspect_topics>","observation":"what the image actually shows, at least one concrete sentence per topic","region":[x,y,w,h]}]}],
"role_findings":[...]} (role_findings is a TOP-LEVEL key of the JSON object, a sibling of "references", not inside it; a file without it is rejected) where region is the part of the image the observation is about, as fractions 0..1; observations must point at different parts (at least three cells of a
3x3 grid) and no two share a region. Your role also writes role_findings (below), one per approved requirement, each with its own region.
Attach it as a completion artifact. The controller verifies your session log: a successful vision_analyze call on each exact reference file must exist, so a
correctly formatted JSON file without the tool calls is rejected. If you cannot open images, finish BLOCKED with blocked_reason naming the missing vision capability; never guess.'''

VISUAL_TRACE = '''Visual traceability: every approved requirement (V ids in approved_references, minus human-approved deferrals) must appear in PLAN.md, in the style
bible rules it affects, and in at least one task: add "visual":["V1",...] to that task in project-plan.json AND state each id in that task's acceptance text.
If the existing style bible (art/style/STYLE.md) forbids, defers or excludes anything an approved reference shows, plan an artist task that amends it:
list the contradicted ids in its "visual", and name the bible path in its acceptance. Never carry a contradicting rule forward.'''

REFERENCE_AUDIT = '''Reference audit (mandatory): compare each derived rule and acceptance criterion with the approved references and the GDD. Every rule, step or
criterion that forbids, defers, excludes or weakens something an approved reference shows is a BLOCKER finding "contradicts <V id>: <rule>" with
finding class architectural. Write the audit as a "Reference audit" section of PLAN-REVIEW.md listing each requirement id and where the plan carries it.
The controller also runs a deterministic contradiction scan over operative rules (style bible, style.json, task acceptance): a rule it flags cannot be approved.
Scan adjudication: PROJECT_CONTEXT.explained_scan_candidates lists lines of plan prose the scan flagged and the author explained (id, text, explanation). Rule on every one in a retained
scan-adjudication.json: {"schema":"factory-scan-adjudication/v1","adjudications":[{"id":"<id>","verdict":"contradiction"|"benign"|"ambiguous","quote":"<15+ characters of the flagged text>",
"rationale":"<40+ characters, judged against the approved image and the surrounding text>"}]}. A contradiction also needs a BLOCKER/HIGH finding naming the id; ambiguous goes to the human.'''

APPROVED_COMPARISON = '''Approved-reference comparison. Judge the real rendered result against the ORIGINAL approved reference images (never against a factory mockup),
requirement by requirement. No similarity score or pixel threshold approves anything here. In comparison.json add "references":[{"id":"<ref id>","sha256":"<sha256>"}]
for every approved reference, and one criterion per approved requirement whose "rule" starts with its V id (for example "V2: ..."), with expected = what the
reference shows and observed = what the retained screenshot shows. Retained screenshots must be real in-engine renders for final integration. Also judge the WHOLE:
open the reference and the screenshots side by side with vision_analyze and add "holistic":{"verdict":"accept"|"reject","summary":"at least 120 characters on how the
whole screenshot compares with the whole reference: would the human who approved it recognise this as the same game?","dimensions":{<each of the reference's inspect_topics>:
"matches"|"close"|"differs"},"screenshots":[retained screenshot names]} and exactly one criterion whose rule starts "HOLISTIC" with the same outcome as the verdict.
Every requirement passing does not make the result acceptable: reject when the overall result does not read as the approved look. Never cite a factory mockup.'''

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

SUPERSEDED = '''Earlier attempts of this stage ({ids}) are superseded. Their verdicts and MANIFEST values do not describe the current state, and the "Recent work" list in your context may still show them as DONE. Only the BASELINE and MANIFEST fields in this card's header apply: BASELINE none means there is no baseline to check, so never run fw.py check --expect with a manifest taken from an earlier attempt or from a "Recent work" entry. Work from the files as they are now.'''

WRITER_GATES = '''failed_checks and checks_failed are only for a check that ran against what this task delivers and failed. A command that cannot run on the frozen copy because it lacks what the command needs is not applicable: do not run it, or if you did,
record it in residual_risk and never in failed_checks. That covers gates that need the whole checkout (Unity compile, EditMode and PlayMode tests, "Not a Unity project"), dependency audits with no package.json or lockfile (npm audit
exiting ENOLOCK), and any tool or editor that is not installed or not part of the manifest. These are writer or publisher gates: confirm the writer's own recorded result in checks_run where one exists. Run a gate on the frozen copy only when that copy
is a complete project (its include list carries the files the gate needs). A real failure on delivered files is still a failed check.'''

CONTINUES = '''This card continues from the files the superseded attempt left on disk. Its MANIFEST and BASELINE are the manifest that attempt reported, so the start check passes only if nothing else changed. Keep what is correct and fix forward; undo only what contradicts this card.'''

STYLE_CHANGED = '''The completed task {id} amended the style bible under art/style/, so the style_sha256 recorded in PLAN.md predates it and must not be used as --expect-style-hash.
If your stage runs the art lint gate, take the expected hash when your stage starts: run art_lint.py PROJECT_DIR --style-hash before you write anything, use that value for --expect-style-hash, and record it in metadata.style_sha256.
A verifier or reviewer on the frozen copy uses the style_sha256 the writer recorded. The gate still fails if art/style changes during the stage.'''

INSPECT_PATHS = '''Open exactly these absolute paths with vision_analyze: {paths}. They are the originals in PROJECT_DIR (reading them there is allowed; zoom crops of an original are fine).
Do not open a copy of an approved image: a copy in a frozen snapshot (src-<sha12>/...), your scratch workspace or an evidence folder is deleted before the stage is checked, so the call cannot be verified and the inspection is rejected, even when the copy is byte-identical.'''

REVIEW_SCOPE = '''Scope of this review: only the requirement ids in this task's visual list ({ids}). Write {kind} findings and declare required tool incidents only for those ids. The other approved requirements belong to other tasks
and to the final integration, which reviews all of them with in-engine Game-view screenshots; an in-engine render of them is not required of this stage, so it is not a tool incident. Still inspect the whole reference image.'''

PLAN_BLOCKED = '''If the task plan or an acceptance criterion is wrong, contradictory or untestable, or the available tools cannot express it, do not work around it and do not weaken the criterion:
finish VERDICT=BLOCKED with blocked_reason naming the criterion and why. The project then stops for a human, who decides. Nothing is sent back to the architect.'''

PLAN_FINDING = '''If a criterion itself is wrong or untestable rather than the implementation, say so in a finding that names the criterion. Repairs are bounded; when the limit is
reached the project stops for a human, who decides. Nothing is sent back to the architect.'''

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
    if project.get('references') and stage.key != 'project-scope':
        details['approved_references'] = project['references']
    if stage.key == 'project-plan-review' and project.get('explained_candidates'):
        resolved = set(project.get('scan_resolved', []))
        open_candidates = [c for group in project['explained_candidates'].values() for c in group if c['id'] not in resolved]
        if open_candidates:
            details['explained_scan_candidates'] = open_candidates
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
