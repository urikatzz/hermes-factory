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


def inspection(loaded, **change):
    reference = refs.authoritative(loaded['references'])[0]
    entry = dict(id=reference['id'], path=reference['path'], sha256=reference['sha256'], tool='vision_analyze',
                 requirement_ids=[q['id'] for q in reference['requirements']],
                 observations=[dict(topic=t, observation=f'Concrete description of the {t} that the reference image really shows') for t in reference['topics']])
    entry.update(change)
    return dict(schema=refs.INSPECTION_SCHEMA, references=[entry])


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

    def finish(self, stage, plan_text, inspected=True, viewed=True, succeeded=True, extra=(), **overrides):
        """Complete a stage the way a worker would: PLAN.md, optional inspection JSON, optional real vision calls in its session log."""
        artifacts = [self.write(stage, 'PLAN.md', plan_text)]
        if inspected:
            artifacts.append(self.write(stage, 'reference-inspection.json', inspection(self.loaded)))
        self.board.complete(stage, artifacts=[*artifacts, *extra], **overrides)
        self.sessions += 1
        session = f'session{self.sessions:04d}{stage["stage_key"].replace("-", "")}'
        row = self.conn.execute('SELECT id,metadata FROM task_runs WHERE task_id=? ORDER BY id DESC', (stage['task_id'],)).fetchone()
        metadata = json.loads(row[1])
        metadata['worker_session_id'] = session
        self.conn.execute('UPDATE task_runs SET metadata=? WHERE id=?', (json.dumps(metadata), row[0]))
        self.conn.commit()
        record_session(self.home, stage['profile'], session, self.reference_files() if viewed else [], succeeded)
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
        self.controller.resume(self.conn, self.root, 'Approved')

    def architect(self, tasks, plan_text=None, **kwargs):
        stage = self.only('architect')
        extra = self.write(stage, 'project-plan.json', dict(tasks=tasks))
        self.finish(stage, plan_text or (self.required_ids() + ' carried by the tasks.'), extra=[extra], **kwargs)

    def visual_task(self, **change):
        ids = [r['id'] for r in refs.required_requirements(self.loaded['references'])]
        return {**dict(id='look', title='Presentation', owner='developer', dependencies=[], needs={**NEEDS, 'art': True}, visual=ids,
                       acceptance={'AC1': ' and '.join(f'{i} is visible in the rendered game' for i in ids)}), **change}
