import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import board_fixture
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.project_evidence import validate_comparison
from factory_dashboard.workflow_handoffs import StageResult


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.plan=dict(profile='art-director',sha256='a'*64)
        self.record=dict(schema='factory-comparison/v1',plan_sha256='a'*64,manifest_sha12='abcdef123456',
                         mode='rendered_asset',source='tool',outcome='pass',
                         criteria=[dict(rule='S1',expected='Rounded silhouette',observed='Rounded silhouette',outcome='pass')],
                         evidence=[str(self.directory/'render.png')])
        (self.directory/'render.png').write_bytes(b'image')

    def result(self):
        path=self.directory/'comparison.json';path.write_text(json.dumps(self.record))
        return StageResult(True,'','review',1,dict(manifest_sha12='abcdef123456',verdict='NO_BLOCKING_FINDINGS',
                                                  artifacts=[str(path),*self.record['evidence']],findings=[]))

    def test_asset_render_is_not_final_in_engine_approval(self):
        result=self.result()
        validate_comparison('art-reviewer',result,[self.plan],False)
        with self.assertRaisesRegex(ConfigurationError,'rendered/listening'):
            validate_comparison('art-reviewer',result,[self.plan],True)

    def test_stale_director_plan_cannot_approve_new_assets(self):
        self.record['plan_sha256']='b'*64
        with self.assertRaisesRegex(ConfigurationError,'director plan'):
            validate_comparison('art-reviewer',self.result(),[self.plan],False)

    def test_audio_measurements_cannot_substitute_for_listening(self):
        self.plan['profile']='audio-director';self.record['mode']='measured'
        with self.assertRaisesRegex(ConfigurationError,'listening'):
            validate_comparison('audio-reviewer',self.result(),[self.plan],False)

    def test_audio_can_use_retained_listening_evaluation(self):
        self.plan['profile']='audio-director';self.record['mode']='listened';self.record['source']='human'
        note=self.directory/'listening.md';note.write_text('Listener: expected bright coin chime; heard bright coin chime.')
        self.record['evidence']=[str(note)]
        validate_comparison('audio-reviewer',self.result(),[self.plan],True)

    def test_listening_claim_with_only_waveform_image_is_rejected(self):
        self.plan['profile']='audio-director';self.record['mode']='listened'
        with self.assertRaisesRegex(ConfigurationError,'listening evaluation'):
            validate_comparison('audio-reviewer',self.result(),[self.plan],False)

    def test_a_director_mismatch_cannot_be_reported_as_nonblocking(self):
        self.record['outcome']='fail';self.record['criteria'][0]['outcome']='fail'
        result=self.result()
        result.metadata.update(verdict='CHANGES_REQUIRED',findings=['F1|LOW|-|render.png|Wrong silhouette'])
        with self.assertRaisesRegex(ConfigurationError,'blocking'):
            validate_comparison('art-reviewer',result,[self.plan],False)

    def test_scratch_evidence_references_resolve_after_attachment_retention(self):
        self.record['evidence']=['/deleted/scratch/render.png']
        result=self.result()
        result.metadata['artifacts']=[str(self.directory/'comparison.json'),str(self.directory/'render.png')]
        validate_comparison('art-reviewer',result,[self.plan],False)


if __name__ == '__main__': unittest.main()
