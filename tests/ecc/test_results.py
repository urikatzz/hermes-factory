import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from factory_ecc.files import read_json, write_json
from factory_ecc.tasksets import load_taskset
from factory_ecc.results import load_trials
from result_fixtures import trial, results

ROOT = Path(__file__).resolve().parents[2] / 'benchmarks/factory-v1'


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.taskset = load_taskset(ROOT)
        self.one = trial(self.root, self.taskset)
        self.path = self.root/'results.json'

    def load(self, document):
        write_json(self.path, document)
        return load_trials(self.taskset, self.path, self.root)

    def change_gate(self, update):
        ref = self.one['evidence']['gate']
        path = self.root/ref['path']; data = read_json(path)
        update(data); write_json(path, data)
        ref['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()

    def test_completed_trial_requires_matching_grade_gate_and_source(self):
        loaded = self.load(results(self.taskset,[self.one]))
        self.assertEqual(loaded[0]['classification'], 'success')
        self.assertTrue(loaded[0]['first_attempt'])
        (self.root/self.one['candidate_source']/'solution.py').write_text('changed')
        with self.assertRaises(ValueError): self.load(results(self.taskset,[self.one]))

    def test_missing_evidence_or_unrecorded_attempts_are_not_first_attempt_success(self):
        (self.root/self.one['evidence']['grades']['path']).unlink()
        loaded = self.load(results(self.taskset,[self.one]))
        self.assertEqual(loaded[0]['classification'],'incomplete')
        self.assertIsNone(loaded[0]['first_attempt'])

    def test_attempt_history_distinguishes_execution_retry_from_repair(self):
        self.change_gate(lambda g: g['writer_attempts'].insert(0, dict(task_id='old',run_id='old',outcome='failed')))
        loaded = self.load(results(self.taskset,[self.one]))
        self.assertFalse(loaded[0]['first_attempt'])
        self.change_gate(lambda g: g.update(attempts_complete=False))
        self.assertIsNone(self.load(results(self.taskset,[self.one]))[0]['first_attempt'])

    def test_incomplete_panel_is_not_success_and_different_manifest_is_error(self):
        self.change_gate(lambda g: g.update(reviewers=[]))
        self.assertEqual(self.load(results(self.taskset,[self.one]))[0]['classification'],'incomplete')
        self.change_gate(lambda g: g.update(source_manifest_sha256='b'*64))
        with self.assertRaises(ValueError): self.load(results(self.taskset,[self.one]))

    def test_schema_duplicates_unknown_cases_boolean_numbers_and_nonfinite_rejected(self):
        good = results(self.taskset,[self.one])
        bads = []
        x=copy.deepcopy(good); x['trials'] *= 2; bads.append(x)
        x=copy.deepcopy(good); x['trials'][0]['case_id']='unknown'; bads.append(x)
        x=copy.deepcopy(good); x['taskset_digest']='0'*64; bads.append(x)
        x=copy.deepcopy(good); x['trials'][0]['repairs']=True; bads.append(x)
        x=copy.deepcopy(good); x['trials'][0]['elapsed_seconds']=-1; bads.append(x)
        x=copy.deepcopy(good); x['trials'][0]['extra']='no'; bads.append(x)
        x=copy.deepcopy(good); x['trials'][0]['synthetic']=False; bads.append(x)
        for value in bads:
            with self.subTest(value=value):
                with self.assertRaises(ValueError): self.load(value)

    def test_conflicting_grade_gate_and_trial_identities_rejected(self):
        self.change_gate(lambda g: g['writer'].update(run_id='other'))
        with self.assertRaises(ValueError): self.load(results(self.taskset,[self.one]))

    def test_escaping_and_symlinked_evidence_rejected(self):
        self.one['evidence']['grades']['path']='../grades.json'
        with self.assertRaises(ValueError): self.load(results(self.taskset,[self.one]))

    def test_infrastructure_blocked_never_becomes_success(self):
        self.one['terminal_outcome']='infrastructure_blocked'
        self.assertEqual(self.load(results(self.taskset,[self.one]))[0]['classification'],'infrastructure_blocked')

    def test_recorded_verifier_failure_counts_as_failed_not_incomplete(self):
        def fail(gate):
            gate['verifier']['verdict']='FAIL'
            gate['verifier']['ac_results']['AC1']='fail'
            gate['decision'].update(decision='human_review', blocking=['AC1: fail'])
        self.change_gate(fail)
        self.assertEqual(self.load(results(self.taskset,[self.one]))[0]['classification'],'failed')

    def test_contradictory_writer_attempt_outcome_is_rejected(self):
        self.change_gate(lambda g:g['writer_attempts'][0].update(outcome='failed'))
        with self.assertRaises(ValueError):self.load(results(self.taskset,[self.one]))

    def test_known_grade_failure_without_gate_is_failed_with_incomplete_coverage(self):
        ref=self.one['evidence']['grades'];path=self.root/ref['path']
        grades=read_json(path);grades['ac_results']['AC1']='fail';write_json(path,grades)
        ref['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.one['evidence']['gate']=None
        self.one['terminal_outcome']='failed'
        loaded=self.load(results(self.taskset,[self.one]))[0]
        self.assertEqual(loaded['classification'],'failed')
        self.assertFalse(loaded['evidence_complete'])

    def test_failed_verifier_attempt_with_failing_ac_is_failed(self):
        def fail(gate):
            gate['verifier'].update(outcome='failed',verdict='FAIL')
            gate['verifier']['ac_results']['AC1']='fail'
            gate['decision'].update(decision='human_review',blocking=['AC1: fail'])
        self.change_gate(fail)
        self.assertEqual(self.load(results(self.taskset,[self.one]))[0]['classification'],'failed')

    def test_malformed_reviewer_profile_has_validation_error(self):
        self.change_gate(lambda g:g['reviewers'][0].update(profile=[]))
        with self.assertRaises(ValueError):self.load(results(self.taskset,[self.one]))
