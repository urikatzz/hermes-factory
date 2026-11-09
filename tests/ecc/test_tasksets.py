import json
from pathlib import Path
import shutil
import tempfile
import unittest

from factory_ecc.tasksets import load_taskset, prepare_case, source_manifest
from factory_ecc.graders import prepare_grading

ROOT = Path(__file__).resolve().parents[2] / 'benchmarks/factory-v1'


class TasksetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_three_cases_prepare_only_public_source_and_instructions(self):
        taskset = load_taskset(ROOT)
        self.assertEqual([c['id'] for c in taskset['cases']], ['bug', 'feature', 'chore'])
        for case in taskset['cases']:
            out = self.root / case['id']
            result = prepare_case(taskset, case['id'], out)
            self.assertEqual(result['taskset_digest'], taskset['digest'])
            self.assertTrue((out / 'source' / 'solution.py').is_file())
            self.assertFalse((out / 'graders').exists())
            self.assertEqual(set(json.loads((out / 'task.json').read_text())),
                             {'case_id', 'taskset_digest', 'prompt', 'acceptance', 'task_type'})
            with self.assertRaises(FileExistsError):
                prepare_case(taskset, case['id'], out)

    def test_tampered_files_and_unknown_cases_are_rejected(self):
        shutil.copytree(ROOT, self.root / 'set')
        path = self.root / 'set/cases/bug/source/solution.py'
        path.write_text('modified')
        with self.assertRaises(ValueError):
            load_taskset(self.root / 'set')
        with self.assertRaises(ValueError):
            prepare_case(load_taskset(ROOT), 'missing', self.root / 'out')

    def test_candidate_links_and_external_paths_rejected(self):
        candidate = self.root / 'candidate'
        candidate.mkdir()
        (candidate / 'solution.py').symlink_to(ROOT / 'cases/bug/source/solution.py')
        with self.assertRaises(ValueError):
            source_manifest(candidate)
        taskset = load_taskset(ROOT)
        taskset['cases'][0]['source'] = ['../../outside']
        with self.assertRaises(ValueError):
            prepare_case(taskset, 'bug', self.root / 'out')

    def test_grading_preparation_keeps_checker_separate_and_records_manifest(self):
        taskset = load_taskset(ROOT)
        prepare_case(taskset, 'bug', self.root / 'worker')
        result = prepare_grading(taskset, 'bug', self.root / 'worker/source', self.root / 'grading')
        self.assertEqual(result['manifest_sha256'], source_manifest(self.root / 'worker/source'))
        self.assertTrue((self.root / 'grading/trusted/grader.py').is_file())
        self.assertFalse((self.root / 'grading/candidate/grader.py').exists())
