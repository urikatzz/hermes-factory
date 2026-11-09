import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from factory_ecc.files import write_json
from factory_ecc.tasksets import load_taskset
from result_fixtures import trial, results

ROOT=Path(__file__).resolve().parents[2]


class CliTests(unittest.TestCase):
    def test_prepare_report_and_invalid_input_preserve_existing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            cli=[sys.executable,str(ROOT/'scripts/factory_benchmark.py')]
            taskset=load_taskset(ROOT/'benchmarks/factory-v1')
            prepared=subprocess.run(cli+['prepare','--taskset',str(taskset['root']),'--case','bug','--output',str(root/'work')],capture_output=True,text=True)
            self.assertEqual(prepared.returncode,0,prepared.stderr)
            one=trial(root,taskset)
            write_json(root/'results.json',results(taskset,[one]))
            command=cli+['report','--taskset',str(taskset['root']),'--results',str(root/'results.json'),
                         '--evidence-root',str(root),'--output',str(root/'report')]
            completed=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertTrue(json.loads((root/'report.json').read_text())['synthetic'])
            saved=(root/'report.md').read_bytes()
            (root/'results.json').write_text('{}')
            failed=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(failed.returncode,2)
            self.assertEqual((root/'report.md').read_bytes(),saved)
            self.assertEqual((root/'report.json').stat().st_mode & 0o777,0o600)

    def test_report_refuses_to_overwrite_evidence_source_or_taskset(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);taskset=load_taskset(ROOT/'benchmarks/factory-v1')
            one=trial(root,taskset)
            write_json(root/'results.json',results(taskset,[one]))
            gate=root/one['evidence']['gate']['path']
            grade=root/one['evidence']['grades']['path']
            source=root/one['candidate_source']/'report.json'
            source.write_text('important source data')
            # Refresh the manifest because this extra source file is part of the candidate.
            from factory_ecc.tasksets import source_manifest
            import hashlib
            from factory_ecc.files import read_json
            one['manifest_sha256']=source_manifest(source.parent)
            for path in (gate,grade):
                data=read_json(path)
                key='source_manifest_sha256' if path==gate else 'manifest_sha256'
                data[key]=one['manifest_sha256'];write_json(path,data)
                ref=one['evidence']['gate' if path==gate else 'grades']
                ref['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            write_json(root/'results.json',results(taskset,[one]))
            for target in (gate,grade,source):
                saved=target.read_bytes()
                command=[sys.executable,str(ROOT/'scripts/factory_benchmark.py'),'report',
                    '--taskset',str(taskset['root']),'--results',str(root/'results.json'),
                    '--evidence-root',str(root),'--output',str(target.with_suffix(''))]
                completed=subprocess.run(command,capture_output=True,text=True)
                self.assertEqual(completed.returncode,2,completed.stdout)
                self.assertEqual(target.read_bytes(),saved)
