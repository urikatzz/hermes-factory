import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/factory-dashboard'))
from factory_dashboard import dry_run_card as dr  # noqa: E402

FW = Path(__file__).resolve().parents[2] / 'runtime/factory-skills/worker/factory-worker/scripts/fw.py'
SCRIPT = Path(__file__).resolve().parents[2] / 'runtime/factory-dashboard/scripts/resume_factory_workflow.py'
BASE = 'a' * 12


def make_snapshot(path, manifest_text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tarfile.open(path, 'w:gz') as tar:
        data = manifest_text.encode(); info = tarfile.TarInfo('.factory/SHA256SUMS'); info.size = len(data); tar.addfile(info, io.BytesIO(data))
    return hashlib.sha256(manifest_text.encode()).hexdigest()[:12]


def card(project, expect, tgz, owned, header_baseline=None):
    header_baseline = header_baseline or expect
    return (f'ROOT t_1 | STAGE FIX | CYCLE 6\\nPROJECT_DIR {project}\\nMANIFEST {header_baseline}\\nBASELINE {header_baseline}   BASELINE_TGZ none\\n'.replace('\\n', '\n')
            + f'Start-of-stage check for this repair: OWNED_PATHS {owned}. Run `fw.py check PROJECT_DIR --expect {expect} --owned "{owned}" --baseline-tgz "{tgz}"` (still mandatory)')


class FingerprintAndIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'board' / 'kanban.db'
        self.db.parent.mkdir()
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE tasks (id TEXT, assignee TEXT, status TEXT, title TEXT, body TEXT, created_at INTEGER)')
        conn.execute("INSERT INTO tasks VALUES ('t_1','artist','done','old','body',1)")
        conn.commit(); conn.close()
        (self.db.parent / 'attachments').mkdir(); (self.db.parent / 'attachments/a.txt').write_text('a')

    def test_a_snapshot_copy_can_be_mutated_without_touching_the_live_board(self):
        before = (dr.fingerprint_db(self.db), dr.fingerprint_tree(self.db.parent))
        scratch = Path(dr.scratch_dir()); self.addCleanup(lambda: __import__('shutil').rmtree(scratch, ignore_errors=True))
        copy = dr.snapshot_board(self.db, scratch)
        conn = sqlite3.connect(copy)
        conn.execute("INSERT INTO tasks VALUES ('t_new','artist','ready','new','the simulated card',2)"); conn.execute("UPDATE tasks SET status='running'"); conn.commit(); conn.close()
        self.assertEqual([t['id'] for t in dr.new_tasks(copy, dr.known_task_ids(self.db))], ['t_new'])   # the copy has the simulated card
        self.assertEqual((dr.fingerprint_db(self.db), dr.fingerprint_tree(self.db.parent)), before)       # the live board does not
        self.assertEqual(dr.known_task_ids(self.db), {'t_1'})

    def test_the_fingerprints_detect_a_database_change_and_a_file_change(self):
        db_before, tree_before = dr.fingerprint_db(self.db), dr.fingerprint_tree(self.db.parent)
        conn = sqlite3.connect(self.db); conn.execute("UPDATE tasks SET status='ready'"); conn.commit(); conn.close()
        self.assertNotEqual(dr.fingerprint_db(self.db), db_before)
        (self.db.parent / 'attachments/b.txt').write_text('new')
        self.assertNotEqual(dr.fingerprint_tree(self.db.parent), tree_before)

    def test_the_fingerprint_ignores_the_database_file_bytes_but_not_its_contents(self):
        before = dr.fingerprint_tree(self.db.parent)
        conn = sqlite3.connect(self.db); conn.execute('PRAGMA journal_mode=WAL'); conn.execute("INSERT INTO tasks VALUES ('t_2','x','done','x','x',3)"); conn.commit(); conn.close()
        self.assertEqual(dr.fingerprint_tree(self.db.parent), before)     # kanban.db* are covered by the logical fingerprint, not the byte one
        self.assertEqual(dr.fingerprint_db(self.db)['rows']['tasks'], 2)


class CardVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'; (self.project / '.factory').mkdir(parents=True)
        for rel in ('Assets/wall.png', 'Assets/floor.png', 'code/main.py'):
            f = self.project / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text('original ' + rel)
        (self.project / '.factory/PLAN.md').write_text('AC1: x\n'); (self.project / '.factory/include.txt').write_text('Assets\ncode\n')
        subprocess.run([sys.executable, str(FW), 'manifest', str(self.project)], check=True, capture_output=True)
        self.manifest = (self.project / '.factory/SHA256SUMS').read_text()
        self.baseline = hashlib.sha256(self.manifest.encode()).hexdigest()[:12]
        self.tgz = str(self.root / 'att/t_x' / ('src-%s.tgz' % self.baseline)); make_snapshot(self.tgz, self.manifest)
        self.owned = 'Assets/wall.png,Assets/floor.png'

    def change(self, *rels):
        for rel in rels:
            (self.project / rel).write_text('changed ' + rel)

    def rebuild(self):
        subprocess.run([sys.executable, str(FW), 'manifest', str(self.project)], check=True, capture_output=True)   # run 212's mutation

    def body(self, **kw):
        return card(self.project, kw.get('expect', self.baseline), kw.get('tgz', self.tgz), kw.get('owned', self.owned), kw.get('header'))

    def test_the_exact_card_passes_every_check_and_its_start_check_exits_zero_after_the_manifest_mutation(self):
        self.change('Assets/wall.png', 'Assets/floor.png'); self.rebuild()
        body = self.body()
        verdict = dr.verify_card(body, self.baseline, ['Assets/wall.png', 'Assets/floor.png'])
        self.assertTrue(verdict['ok'], verdict['checks'])
        before = dr.fingerprint_tree(self.project)
        code, out = dr.run_start_check(body, FW)
        self.assertEqual((code, out['ok']), (0, True))
        self.assertEqual(sorted(out['start_check']['accepted_owned']), ['Assets/floor.png', 'Assets/wall.png'])
        self.assertTrue(out['start_check']['manifest_rebuilt_since_baseline'])
        self.assertEqual(dr.fingerprint_tree(self.project), before)       # the check does not modify the worktree

    def test_a_header_or_expect_carrying_the_mutated_manifest_fails_verification(self):
        mutated = '2a733f8c645d'
        self.assertFalse(dr.verify_card(self.body(header=mutated), self.baseline, ['Assets/wall.png', 'Assets/floor.png'])['checks']['header_baseline'])
        bad = dr.verify_card(self.body(expect=mutated), self.baseline, ['Assets/wall.png', 'Assets/floor.png'])
        self.assertFalse(bad['ok']); self.assertFalse(bad['checks']['explicit_expect'])
        self.change('Assets/wall.png', 'Assets/floor.png'); self.rebuild()
        code, out = dr.run_start_check(self.body(expect=mutated), FW)
        self.assertEqual(code, 5)                                          # fw refuses: the snapshot is not the expected baseline

    def test_a_snapshot_that_does_not_hold_the_baseline_fails_content_verification_and_the_start_check(self):
        liar = str(self.root / 'att/t_y' / ('src-%s.tgz' % self.baseline)); make_snapshot(liar, 'some other manifest\n')
        verdict = dr.verify_card(self.body(tgz=liar), self.baseline, ['Assets/wall.png', 'Assets/floor.png'])
        self.assertTrue(verdict['checks']['snapshot_named_for_baseline']); self.assertFalse(verdict['checks']['snapshot_content_matches']); self.assertFalse(verdict['ok'])
        self.change('Assets/wall.png'); code, _ = dr.run_start_check(self.body(tgz=liar), FW)
        self.assertEqual(code, 5)

    def test_the_owned_set_must_be_exactly_the_wall_and_floor(self):
        for owned in ('Assets/wall.png', 'Assets/wall.png,Assets/floor.png,code/main.py', 'Assets/wall.png,Assets/wall.png,Assets/floor.png'):
            with self.subTest(owned=owned):
                self.assertFalse(dr.verify_card(self.body(owned=owned), self.baseline, ['Assets/wall.png', 'Assets/floor.png'])['checks']['owned_exact'])

    def test_an_unrelated_change_makes_the_cards_start_check_fail_closed(self):
        self.change('Assets/wall.png', 'Assets/floor.png', 'code/main.py'); self.rebuild()
        code, out = dr.run_start_check(self.body(), FW)
        self.assertEqual((code, out['ok'], out['mismatched']), (4, False, ['code/main.py']))

    def test_a_card_without_a_start_check_line_is_reported_not_run(self):
        self.assertEqual(dr.run_start_check('PROJECT_DIR /x\nno check here', FW)[0], None)
        self.assertFalse(dr.verify_card('no check here', self.baseline, ['a'])['ok'])


if __name__ == '__main__':
    unittest.main()
