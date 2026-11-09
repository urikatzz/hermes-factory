from pathlib import Path
import tempfile
import unittest
from factory_ecc.files import write_json
from factory_ecc.tasksets import load_taskset
from factory_ecc.results import load_trials
from factory_ecc.reporting import summarize, render_markdown
from result_fixtures import trial, results, variant

ROOT=Path(__file__).resolve().parents[2]/'benchmarks/factory-v1'


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.taskset=load_taskset(ROOT)

    def report(self, document):
        path=self.root/'results.json';write_json(path,document)
        return summarize(self.taskset,load_trials(self.taskset,path,self.root))

    def test_rates_expose_denominators_coverage_and_synthetic_label(self):
        one=trial(self.root,self.taskset)
        two=trial(self.root,self.taskset,'2');two['terminal_outcome']='infrastructure_blocked'
        report=self.report(results(self.taskset,[one,two]))
        row=report['variants'][0]
        self.assertEqual(row['eventual_success'],dict(successes=1,denominator=1,rate=1.0))
        self.assertEqual(row['counts'],dict(success=1,failed=0,infrastructure_blocked=1,incomplete=0))
        self.assertEqual(row['cases']['feature']['imported'],0)
        self.assertTrue(report['synthetic'])
        self.assertIn('SYNTHETIC',render_markdown(report))

    def test_shared_sessions_deduplicate_and_are_not_apportioned_across_variants(self):
        one=trial(self.root,self.taskset)
        two=trial(self.root,self.taskset,'2',variant_id='candidate')
        session=dict(id='board/profile/session-1',actual_usd=1.25,estimate_usd=2.0,included=False,
                     input_tokens=100,output_tokens=30,cache_read_tokens=None,cache_write_tokens=None,reasoning_tokens=None)
        one['sessions']=[session];two['sessions']=[dict(session)]
        report=self.report(results(self.taskset,[one,two],[variant(),variant('candidate')]))
        self.assertEqual(report['usage']['actual_usd'],1.25)
        self.assertEqual(report['usage']['shared_session_ids'],[session['id']])
        self.assertEqual(report['variants'][0]['usage']['actual_usd'],None)
        self.assertEqual(report['usage']['input_tokens'],100)

    def test_unknown_and_subscription_costs_are_not_zero_or_estimate_charges(self):
        one=trial(self.root,self.taskset)
        report=self.report(results(self.taskset,[one]))
        self.assertIsNone(report['usage']['actual_usd'])
        self.assertEqual(report['usage']['trials_without_sessions'],1)
        one['sessions']=[dict(id='included',actual_usd=None,estimate_usd=9.0,included=True,
            input_tokens=None,output_tokens=None,cache_read_tokens=None,cache_write_tokens=None,reasoning_tokens=None)]
        report=self.report(results(self.taskset,[one]))
        self.assertIsNone(report['usage']['estimate_usd'])
        self.assertEqual(report['usage']['included_sessions'],1)

    def test_conflicting_session_records_are_rejected(self):
        one=trial(self.root,self.taskset)
        session=dict(id='s',actual_usd=1,estimate_usd=None,included=False,input_tokens=None,
                     output_tokens=None,cache_read_tokens=None,cache_write_tokens=None,reasoning_tokens=None)
        one['sessions']=[session,{**session,'actual_usd':2}]
        with self.assertRaises(ValueError):self.report(results(self.taskset,[one]))
