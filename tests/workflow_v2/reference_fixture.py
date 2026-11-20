"""Shared harness: a project with an approved visual reference driven through the real project controller."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from board_fixture import Board
from factory_dashboard import project_references as refs
from factory_dashboard.workflow_controller import WorkflowController
from factory_dashboard.workflow_state import WorkflowState
from factory_dashboard.workflow_templates import _preset

NEEDS = dict(art=False, audio=False, ui=False, ux=False)
ART = {**NEEDS, 'art': True}
TOPICS = ('composition', 'palette', 'hud', 'subjects', 'materials', 'lighting')
VISION_PROFILES = ['art-director', 'architect', 'claude-reviewer', 'art-reviewer']


def write_project(root, references, png=b'approved-reference-bytes', png_path='docs/look/reference.png', file='docs/references.json', extra=None):
    root = Path(root)
    (root / png_path).parent.mkdir(parents=True, exist_ok=True)
    (root / png_path).write_bytes(png)
    (root / file).parent.mkdir(parents=True, exist_ok=True)
    (root / file).write_text(json.dumps(dict(schema=refs.REFERENCES_SCHEMA, references=references, **(extra or {}))))
    return refs.load_references(root)


REGIONS = [[0.0, 0.0, 0.3, 0.2], [0.35, 0.0, 0.3, 0.2], [0.7, 0.0, 0.3, 0.2], [0.0, 0.4, 0.3, 0.2], [0.35, 0.4, 0.3, 0.2], [0.7, 0.4, 0.3, 0.2],
           [0.0, 0.7, 0.3, 0.2], [0.35, 0.7, 0.3, 0.2]]
ART_PLAN_BLOCK = """
## How the direction is achieved
Assets are built to the approved image.
## Production assets to create
Sprites, panels and interface parts.
## Generated versus procedural
Painted parts are generated; layout is procedural.
## Articulation and animation
Jointed parts are rigged.
## Environment, lighting and interface
Composition, light and HUD are built in the engine.
## Comparison with the reference
Real renders are judged requirement by requirement and as a whole.
## Requirements by milestone
Demanded requirements are active now.
## Representative mockup
See plan-mockup.png; it is subordinate to the approved reference.
"""


def png(width=1280, height=720, size=24000):
    import struct
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', width, height) + b'\x08\x02\x00\x00\x00' + b'\0' * size


def role_findings(loaded, kind, tasks=(), screenshots=(), **per_requirement):
    """One valid, distinct, grounded finding per demanded requirement for the given role kind."""
    result = []
    for index, requirement in enumerate(refs.required_requirements(loaded['references'])):
        identifier = requirement['id']
        entry = dict(kind=kind, requirement_id=identifier, region=REGIONS[index % len(REGIONS)],
                     finding=f'In the image the area shows detail number {index} for this requirement, which leads to a concrete consequence for the work')
        if kind == 'achieve':
            entry['subject'] = 'generated'
        elif kind == 'carry':
            entry['subject'] = next((t['id'] for t in tasks if identifier in t.get('visual', [])), 'none')
        elif kind == 'plan_check':
            entry['verdict'] = 'faithful'
        elif kind == 'render_check':
            entry.update(verdict='matches', subject=screenshots[0] if screenshots else 'missing.png')
        entry.update(per_requirement.get(identifier, {}))
        result.append(entry)
    return result


def inspection(loaded, kind='achieve', tasks=(), screenshots=(), per_requirement=None, **change):
    reference = refs.authoritative(loaded['references'])[0]
    entry = dict(id=reference['id'], path=reference['path'], sha256=reference['sha256'], tool='vision_analyze',
                 requirement_ids=[q['id'] for q in reference['requirements']],
                 observations=[dict(topic=t, region=REGIONS[i % len(REGIONS)], observation=f'Concrete description of the {t} that the reference image really shows') for i, t in enumerate(reference['topics'])])
    entry.update(change)
    return dict(schema=refs.INSPECTION_SCHEMA, references=[entry], role_findings=role_findings(loaded, kind, tasks, screenshots, **(per_requirement or {})))


def record_session(home, profile, session, viewed=(), succeeded=True):
    """A worker session log (the profile's state.db) with one vision_analyze call per viewed image."""
    path = Path(home) / 'profiles' / profile / 'state.db'
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT)')
    for index, image in enumerate(viewed):
        call = f'call_{session}_{index}'
        connection.execute('INSERT INTO messages(session_id,role,tool_calls) VALUES(?,?,?)', (session, 'assistant', json.dumps(
            [dict(id=call, type='function', function=dict(name='vision_analyze', arguments=json.dumps(dict(image_url=str(image), question='Describe it'))))])))
        connection.execute('INSERT INTO messages(session_id,role,tool_call_id,tool_name,content) VALUES(?,?,?,?,?)', (
            session, 'tool', call, 'vision_analyze', 'Image loaded into your context' if succeeded else json.dumps(dict(error='Image could not be decoded', success=False))))
    connection.commit()
    connection.close()


class ReferenceFlow(unittest.TestCase):
    """Subclasses set REFERENCES (the references file content) and may adjust files in prepare()."""
    REFERENCES = []
    REFERENCE_PATH = 'docs/look/reference.png'
    REFERENCES_FILE = 'docs/references.json'
    EXTRA = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'game'
        self.project.mkdir()
        self.prepare()
        self.loaded = refs.load_references(self.project) if self.REFERENCES or (self.project / self.REFERENCES_FILE).exists() or self.gdd_adopted() else None
        self.home = Path(self.temp.name) / 'home'
        self.vision(VISION_PROFILES)
        previous = os.environ.get('FACTORY_HERMES_HOME')
        os.environ['FACTORY_HERMES_HOME'] = str(self.home)
        self.addCleanup(lambda: os.environ.pop('FACTORY_HERMES_HOME') if previous is None else os.environ.__setitem__('FACTORY_HERMES_HOME', previous))
        self.board = Board(self.temp.name)
        self.addCleanup(self.board.conn.close)
        self.conn = self.board.conn
        self.state = WorkflowState()
        self.state.initialize(self.conn)
        definition = {**_preset('feature'), 'execution_version': 2, 'max_repairs': 2}
        self.root = self.board.create_task(self.conn, title='FACTORY: build', body='PROJECT_MODE: existing\nPROJECT_DIR: ' + str(self.project) + '\nREQUEST: Build the game',
                                           assignee='factory-orchestrator')
        self.conn.execute('INSERT INTO factory_workflow_roots(root_id,snapshot_id,definition,phase) VALUES(?,?,?,?)', (self.root, 's', json.dumps(definition), 'preparing'))
        self.conn.commit()
        self.controller = WorkflowController(self.board, self.state, self.temp.name)
        self.sessions = 0

    def prepare(self):
        write_project(self.project, self.REFERENCES, png_path=self.REFERENCE_PATH, file=self.REFERENCES_FILE, extra=self.EXTRA)

    def gdd_adopted(self):
        return bool(refs._synthesized(self.project))

    def vision(self, profiles, blind=()):
        for name in [*profiles, *blind]:
            folder = self.home / 'profiles' / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'config.yaml').write_text('platform_toolsets:\n  cli:\n  - kanban\n' + ('  - vision\n' if name in profiles else ''))

    def tick(self):
        return self.controller.reconcile(self.conn, self.root)

    def document(self):
        return json.loads(self.conn.execute('SELECT document FROM factory_project_execution').fetchone()[0])

    def terminal(self):
        return self.document()['terminal']

    def only(self, profile):
        rows = self.board.ready()
        self.assertEqual([r['profile'] for r in rows], [profile])
        return rows[0]

    def write(self, stage, name, content):
        folder = Path(self.temp.name) / 'out' / f'{stage["stage_key"]}-{stage["cycle"]}-{stage["evidence_retry"]}'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(content if isinstance(content, str) else json.dumps(content))
        return str(path)

    def reference_files(self):
        return [self.project / r['path'] for r in refs.authoritative(self.loaded['references'])]

    def finish(self, stage, plan_text, inspected=True, viewed=True, succeeded=True, extra=(), tasks=(), screenshots=(), per_requirement=None,
               mockup=True, art_plan=True, document='PLAN.md', inspection_change=None, shots_viewed=None, duplicates=False, **overrides):
        """Complete a stage the way a worker would: its document, the inspection JSON with role findings, real vision calls in its session log.

        An art-director stage also gets the art-plan headings and a representative mockup (both can be switched off)."""
        director = stage['profile'] == 'art-director'
        if director and art_plan:
            plan_text += ART_PLAN_BLOCK
        artifacts = [self.write(stage, document, plan_text)]
        seen = list(self.reference_files()) if viewed else []
        if director and mockup:
            folder = Path(self.temp.name) / 'out' / f'{stage["stage_key"]}-{stage["cycle"]}-{stage["evidence_retry"]}'
            (folder / 'plan-mockup.png').write_bytes(png())
            artifacts.append(str(folder / 'plan-mockup.png'))
            if viewed:
                seen.append(Path(self.temp.name) / 'gone-scratch' / 'plan-mockup.png')  # the director opened its scratch copy, deleted by the time it is checked
        if inspected:
            kind = refs.role_kind(stage['profile'], stage['stage_key'])
            artifacts.append(self.write(stage, 'reference-inspection.json', inspection(self.loaded, kind, tasks, screenshots, per_requirement, **(inspection_change or {}))))
        if shots_viewed:
            seen.extend(shots_viewed)
        listed = [*artifacts, *extra]
        if duplicates:
            # Kanban attaches a file once per mention (artifacts argument and metadata.artifacts): numbered copies with the same bytes.
            for path in list(listed):
                source = Path(path)
                copy = source.with_name(source.stem + '_1' + source.suffix)
                copy.write_bytes(source.read_bytes() if duplicates is True else (source.read_bytes() + b' ' if source.suffix == '.json' else source.read_bytes()))
                listed.append(str(copy))
        self.board.complete(stage, artifacts=listed, **overrides)
        self.sessions += 1
        session = f'session{self.sessions:04d}{stage["stage_key"].replace("-", "")}'
        row = self.conn.execute('SELECT id,metadata FROM task_runs WHERE task_id=? ORDER BY id DESC', (stage['task_id'],)).fetchone()
        metadata = json.loads(row[1])
        metadata['worker_session_id'] = session
        self.conn.execute('UPDATE task_runs SET metadata=? WHERE id=?', (json.dumps(metadata), row[0]))
        self.conn.commit()
        record_session(self.home, stage['profile'], session, seen, succeeded)
        self.tick()

    def rejection(self, profile):
        stage = self.only(profile)
        body = self.board.cards[stage['task_id']]['body']
        return stage, json.JSONDecoder().raw_decode(body.rsplit('\nPROJECT_CONTEXT ', 1)[1])[0]

    def start(self):
        self.tick()
        self.board.complete(self.only('factory-orchestrator'), project_scope=ART)
        self.tick()

    def required_ids(self):
        return ' '.join(r['id'] for r in refs.required_requirements(self.loaded['references']))

    def approved_director(self, plan=None):
        self.start()
        self.finish(self.only('art-director'), plan or ('Carry ' + self.required_ids() + ' into the bible and tasks.'))
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        awaiting = self.document()['awaiting']
        self.controller.resume(self.conn, self.root, f"APPROVE {self.root} {awaiting['sha256'][:12]} {(awaiting.get('references_digest') or 'none')[:12]} Approved")

    def architect(self, tasks, plan_text=None, **kwargs):
        stage = self.only('architect')
        extra = self.write(stage, 'project-plan.json', dict(tasks=tasks))
        self.finish(stage, plan_text or (self.required_ids() + ' carried by the tasks.'), extra=[extra], tasks=tasks, **kwargs)

    def visual_task(self, **change):
        ids = [r['id'] for r in refs.required_requirements(self.loaded['references'])]
        return {**dict(id='look', title='Presentation', owner='developer', dependencies=[], needs={**NEEDS, 'art': True}, visual=ids,
                       acceptance={'AC1': ' and '.join(f'{i} is visible in the rendered game' for i in ids)}), **change}
