"""Immutable template revisions with optimistic edits and replaceable type defaults."""
from dataclasses import asdict
import json
import uuid
from .model_policy import ConfigurationError
from .policy_store import RevisionConflict
from .task_settings_store import encode
from .workflow_types import WorkflowDefinition, TASK_TYPES


LINT = "art_lint.py from the art-review skill (the skill's LINT line gives its absolute path)"
GAME_ART = {
    'description': 'Art Director plans, Artist produces (Codex concept, Tripo or Blender blockout, Blender cleanup), art-reviewer and claude-reviewer review, verifier runs the art lint gate.',
    'prepare': ('Plan game art as the art-director SOUL says. First look for a style bible: art/style/STYLE.md and art/style/style.json under PROJECT_DIR (the art_lint.py bible validator is not a gate). '
                'Style task (the request asks for a style bible, or none exists and the request is about style): specify STYLE.md rules with IDs and (blocking) marks, style.json classes, the palette and 2-3 reference images with prompts; ACs require that STYLE.md, style.json and the references exist and that the rules follow the approved references. '
                'Asset task without a valid bible: complete VERDICT=BLOCKED with blocked_reason "no approved style bible: submit an Art task asking for a style bible". '
                'Otherwise list every asset with target path (matching a style.json class), kind (sprite or model), concept prompt, class limits and STYLE rule IDs; one AC per asset plus "art_lint reports no BLOCKER or HIGH"; include list: art/style/, every target path and art/concepts/<name>.png for each model. '
                'For an asset task run python3 <art_lint.py> <PROJECT_DIR> --style-hash and record its value in PLAN.md as style_sha256: <hex>.'),
    'implement': ('Make the planned art with the art-production skill (artist SOUL). Before completing run the art lint gate on PROJECT_DIR: python3 <art_lint.py> <PROJECT_DIR> <changed art paths> --out <PROJECT_DIR>/.factory/tmp/art-lint --fail-on-blocking, where art_lint.py is ' + LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> in an asset task. '
                  'Record it in checks_run, and assets, fallbacks and tripo_tasks in metadata. An asset task never writes art/style/.'),
    'repair': 'Regenerate or refit only the assets named in SCOPE findings with the art-production skill, never art/style/ in an asset task, and rerun the art lint gate (with --expect-style-hash <style_sha256 from PLAN.md> in an asset task) before completing. Never call Tripo again for an asset with a recorded Tripo task or unknown-create; record new Tripo task IDs.',
    'verify': ('Run the art lint gate on the frozen copy as a required check: python3 <art_lint.py> <src_dir> --out "$HERMES_KANBAN_WORKSPACE/art-lint" --fail-on-blocking, where art_lint.py is ' + LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> when PLAN.md records one (asset task). '
               'Exit 1 means a BLOCKER or HIGH lint finding: record the command in failed_checks and fail the AC it threatens. Blender missing makes the affected model ACs unverified:environment. Attach art-lint/lint.json.'),
    'claude-reviewer': 'Review the changed scripts, JSON (style.json, text tables) and engine import settings (.meta files) for correctness. Do not judge art taste or style; art-reviewer does that.',
    'art-reviewer': 'Follow the art-review skill in factory mode.',
}

AUDIO_LINT = "audio_lint.py from the audio-review skill (the skill's LINT line gives its absolute path)"
GAME_AUDIO = {
    'description': 'Audio Director plans, Sound Designer synthesizes WAV effects or processes your Suno files into OGG music, claude-reviewer reviews, verifier runs the audio lint gate.',
    'prepare': ('Plan game audio as the audio-director SOUL says. First check the sound bible: python3 <audio_lint.py> <PROJECT_DIR> --check-bible, where audio_lint.py is ' + AUDIO_LINT + '. '
                'If it exits 1 and the prompt does not ask for a sound bible, complete VERDICT=BLOCKED with blocked_reason "no approved sound bible: submit an Audio task asking for a sound bible". '
                'Otherwise record audio_task: style|sfx|music-cues|music-import in PLAN.md, one AC per asset or cue plus "audio_lint reports no BLOCKER or HIGH" (not for style or music-cues), and the include list from the SOUL. '
                'For every task except style run python3 <audio_lint.py> <PROJECT_DIR> --style-hash and record style_sha256: <hex> in PLAN.md.'),
    'implement': ('Make the planned audio with the audio-production skill (sound-designer SOUL). Before completing run the audio lint gate: python3 <audio_lint.py> <PROJECT_DIR> <changed audio paths> --out <PROJECT_DIR>/.factory/tmp/audio-lint --fail-on-blocking, where audio_lint.py is ' + AUDIO_LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> when PLAN.md records one. '
                  'Record it in checks_run, and assets and missing in metadata. Never write audio/style/ outside a style task, never write audio/incoming/.'),
    'repair': 'Change only the recipes or processing of the assets named in SCOPE findings with the audio-production skill, never audio/style/ outside a style task and never audio/incoming/, and rerun the audio lint gate (with --expect-style-hash when PLAN.md records style_sha256) before completing.',
    'verify': ('Run the audio lint gate on the frozen copy as a required check: python3 <audio_lint.py> <src_dir> --out "$HERMES_KANBAN_WORKSPACE/audio-lint" --fail-on-blocking, where audio_lint.py is ' + AUDIO_LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> when PLAN.md records one. '
               'Exit 1 means a BLOCKER or HIGH lint finding: record the command in failed_checks and fail the AC it threatens. ffmpeg missing makes affected ACs unverified:environment. Missing Suno files listed under missing are not failures. Attach audio-lint/lint.json.'),
    'claude-reviewer': 'Review the changed recipes, cue sheets, audio.json and any engine import settings for correctness and consistency with PLAN.md. Do not judge how it sounds.',
}


def _preset(kind):
    prepare, implement, reviewers = {
        'feature': ('architect', 'developer', ('claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer')),
        'bug': ('fixer', 'fixer', ('claude-reviewer', 'security-reviewer')),
        'chore': ('developer', 'developer', ('claude-reviewer',)),
        'art': ('art-director', 'artist', ('art-reviewer', 'claude-reviewer')),
        'audio': ('audio-director', 'sound-designer', ('claude-reviewer',)),
    }[kind]
    def stage(key, profile, instructions='', stage_kind=None):
        return dict(key=key, kind=stage_kind or key, profile=profile, instructions=instructions)
    instructions = {'feature': 'Design the change and observable acceptance criteria.', 'bug': 'Diagnose the root cause and plan a regression test that fails before the repair and passes afterward.', 'chore': 'Define the scope and demonstrate no unintended behavior change.', 'art': GAME_ART['prepare'], 'audio': GAME_AUDIO['prepare']}
    notes = {'art': GAME_ART, 'audio': GAME_AUDIO}.get(kind, {})
    writer = {'art': 'artist', 'audio': 'sound-designer'}.get(kind, 'fixer')
    return dict(template_id=str(uuid.uuid4()), revision=1, name={'feature':'Feature', 'bug':'Bug fix', 'chore':'Chore', 'art':'Game Art', 'audio':'Game Audio'}[kind], description=notes.get('description', ''), task_type=kind,
                prepare=stage('prepare', prepare, instructions[kind]), implement=stage('implement', implement, notes.get('implement', '')),
                reviewers=[stage(p, p, notes.get(p, ''), stage_kind='review') for p in reviewers], verify=stage('verify', 'verifier', notes.get('verify', '')),
                repair=stage('repair', writer, notes.get('repair', '')), max_repairs=2 if kind in ('art', 'audio') else 3)


class WorkflowTemplates:
    def __init__(self, store):
        self._store = store

    def initialize(self):
        with self._store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_templates(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, archived INTEGER NOT NULL DEFAULT 0)')
            conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_revisions(template_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY(template_id,revision))')
            conn.execute('CREATE TABLE IF NOT EXISTS factory_workflow_defaults(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, templates TEXT NOT NULL)')
            if not conn.execute('SELECT 1 FROM factory_workflow_defaults').fetchone():
                mapping = {}
                for kind in TASK_TYPES:
                    doc = _preset(kind)
                    self._insert(conn, doc)
                    mapping[kind] = doc['template_id']
                conn.execute('INSERT INTO factory_workflow_defaults VALUES(1,1,?)', (encode(mapping),))

    @staticmethod
    def _insert(conn, doc):
        conn.execute('INSERT INTO factory_workflow_templates VALUES(?,?,0)', (doc['template_id'], doc['revision']))
        conn.execute('INSERT INTO factory_workflow_revisions VALUES(?,?,?)', (doc['template_id'], doc['revision'], encode(doc)))

    def defaults(self, conn=None):
        if conn is None:
            with self._store._connect() as c:
                return self.defaults(c)
        row = conn.execute('SELECT revision,templates FROM factory_workflow_defaults WHERE id=1').fetchone()
        return dict(revision=row['revision'], templates=json.loads(row['templates']))

    def get(self, template_id, revision=None, *, conn=None, active=False):
        if conn is None:
            with self._store._connect() as c:
                return self.get(template_id, revision, conn=c, active=active)
        head = conn.execute('SELECT * FROM factory_workflow_templates WHERE id=?', (template_id,)).fetchone()
        if not head or (active and head['archived']):
            raise ConfigurationError('Workflow is missing or archived')
        row = conn.execute('SELECT document FROM factory_workflow_revisions WHERE template_id=? AND revision=?', (template_id, head['revision'] if revision is None else revision)).fetchone()
        if not row:
            raise ConfigurationError('Workflow revision is missing')
        return WorkflowDefinition.from_document(json.loads(row[0]))

    def list(self, include_archived=False):
        with self._store._connect() as conn:
            rows = conn.execute('SELECT * FROM factory_workflow_templates ORDER BY rowid').fetchall()
            return [dict(asdict(self.get(r['id'], conn=conn)), archived=bool(r['archived'])) for r in rows if include_archived or not r['archived']]

    def save(self, document, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise RevisionConflict('Invalid workflow revision')
        data = dict(document)
        template_id = data.get('template_id')
        if expected_revision == 0:
            if template_id or 'revision' in data:
                raise ConfigurationError('New template IDs and revisions are assigned by the server')
            template_id = str(uuid.uuid4())
        data.update(template_id=template_id, revision=expected_revision + 1)
        definition = WorkflowDefinition.from_document(data)
        with self._store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if expected_revision == 0:
                self._insert(conn, asdict(definition))
            else:
                changed = conn.execute('UPDATE factory_workflow_templates SET revision=? WHERE id=? AND revision=? AND archived=0', (definition.revision, template_id, expected_revision))
                if changed.rowcount != 1:
                    raise RevisionConflict('Workflow changed or was archived; reload and review')
                conn.execute('INSERT INTO factory_workflow_revisions VALUES(?,?,?)', (template_id, definition.revision, encode(asdict(definition))))
        return definition

    def archive(self, template_id, expected_revision):
        self._set_archive(template_id, expected_revision, True)

    def restore(self, template_id, expected_revision):
        self._set_archive(template_id, expected_revision, False)

    def _set_archive(self, template_id, expected_revision, archived):
        with self._store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if archived and template_id in self.defaults(conn)['templates'].values():
                raise ConfigurationError('Choose a replacement type default before archiving')
            changed = conn.execute('UPDATE factory_workflow_templates SET archived=? WHERE id=? AND revision=?', (int(archived), template_id, expected_revision))
            if changed.rowcount != 1:
                raise RevisionConflict('Workflow changed; reload and review')

    def set_type_default(self, task_type, template_id, expected_revision):
        if task_type not in TASK_TYPES:
            raise ConfigurationError('Unsupported task type')
        with self._store._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            self.get(template_id, conn=conn, active=True)
            mapping = self.defaults(conn)
            if type(expected_revision) is not int or mapping['revision'] != expected_revision:
                raise RevisionConflict('Workflow defaults changed; reload and review')
            mapping['templates'][task_type] = template_id
            conn.execute('UPDATE factory_workflow_defaults SET revision=revision+1,templates=? WHERE id=1', (encode(mapping['templates']),))
            return self.defaults(conn)
