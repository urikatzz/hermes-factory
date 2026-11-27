"""Structured human rulings: stable fingerprints, claim matching, file-bound reopening and deterministic gate enforcement."""
import json
import tempfile
import unittest
from pathlib import Path

from factory_dashboard import finding_rulings as fr
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.project_decisions import normalize_decisions
from factory_dashboard.workflow_gate import evaluate_cycle
from factory_dashboard.workflow_handoffs import StageResult

META = 'Assets/Art/Room01/door-open.png.meta'
PIVOT_F2 = 'claude-reviewer:F2|HIGH|AC3|' + META + ':136-137|Sprite-level pivot stored (0,0); the sprite will not be centred'
PIVOT_F1 = 'claude-reviewer:F1|HIGH|AC3|' + META + ':140 (also wall-backdrop meta)|Stored sprite pivot (0,0) contradicts the importer spritePivot (0.5,0.5)'
PIVOT_REPHRASED = 'claude-reviewer:F4|BLOCKER|AC3|' + META + '|The alignment data leaves the door anchored at its corner'
NEW_DEFECT = 'claude-reviewer:F3|HIGH|AC3|' + META + ':12|Texture compression is set to uncompressed RGBA32, doubling memory'
OTHER_FILE = 'claude-reviewer:F1|HIGH|AC3|Assets/Art/Room01/platform.png.meta:136|Sprite-level pivot stored (0,0)'


def ruling(**overrides):
    return {**dict(task='scene-env-wiring', ac='AC3', paths=[META], source='claude-reviewer', claim=['pivot', 'alignment'],
                   verdict='false_positive', reason='Alignment 0 is Center; Unity ignores the stored pivot unless alignment is Custom (9)',
                   evidence=[dict(kind='test', ref='Room01PresentationTests.SavedScene_PaintedSpritesHaveCentredPivot',
                                  summary='EditMode 6/6 passed; sprite.pivot == rect/2 on the loaded sprites')],
                   watch=['Assets/Tests/Room01PresentationTests.cs']), **overrides}


def result(findings, profile='claude-reviewer'):
    return StageResult(True, '', 'review', 1, dict(verdict='CHANGES_REQUIRED' if findings else 'NO_BLOCKING_FINDINGS', manifest_sha12='abcdef123456',
                                                    source_profile=profile, findings=[f.split(':', 1)[1] for f in findings]))


WRITER = StageResult(True, '', 'write', 1, dict(verdict='DONE', manifest_sha12='abcdef123456', ac_ids=['AC3']))
VERIFIER = StageResult(True, '', 'verify', 1, dict(verdict='PASS', manifest_sha12='abcdef123456', source_profile='verifier', ac_ids=['AC3'],
                                                   ac_results={'AC3': 'pass'}, release_audit='PASS', findings=[], failed_checks=[], checks_failed=0))


class RulingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        for path in (META, 'Assets/Art/Room01/platform.png.meta', 'Assets/Tests/Room01PresentationTests.cs'):
            (self.dir / path).parent.mkdir(parents=True, exist_ok=True); (self.dir / path).write_text('v1 ' + path)
        self.project = {}
        fr.merge(self.project, fr.normalize_rulings([ruling()], 'Human recovery: pivot is a false positive', self.dir, now=1))

    def gate(self, findings, max_repairs=3, used=3, task='scene-env-wiring'):
        return evaluate_cycle(WRITER, [VERIFIER, result(findings)], None, max_repairs, used,
                              dict(task_id=task, rulings=self.project['rulings'], waivers=[]))

    # fingerprints
    def test_fingerprint_ignores_reviewer_numbering_severity_lines_and_wording(self):
        prints = {fr.fingerprint(f, 'scene-env-wiring') for f in (PIVOT_F2, PIVOT_F1, PIVOT_REPHRASED, NEW_DEFECT)}
        self.assertEqual(len(prints), 1)
        self.assertNotEqual(fr.fingerprint(PIVOT_F2, 'scene-env-wiring'), fr.fingerprint(PIVOT_F2, 'other-task'))
        self.assertNotEqual(fr.fingerprint(PIVOT_F2, 'scene-env-wiring'), fr.fingerprint(OTHER_FILE, 'scene-env-wiring'))
        self.assertIn(fr.fingerprint(PIVOT_F2, 'scene-env-wiring'), self.project['rulings'][0]['fingerprints'])

    # the gate
    def test_a_renumbered_finding_is_dismissed_even_at_the_repair_limit(self):
        for finding in (PIVOT_F2, PIVOT_F1):
            decision = self.gate([finding])
            self.assertEqual(decision.decision, 'pass', finding)
            self.assertIn('dismissed by human ruling ' + self.project['rulings'][0]['id'], decision.waived[0])
            self.assertIn(finding, decision.waived[0])  # the original text is kept

    def test_a_rephrased_finding_with_a_claim_term_is_dismissed(self):
        self.assertEqual(self.gate([PIVOT_REPHRASED]).decision, 'pass')

    def test_repeated_reviews_never_consume_repairs(self):
        for cycle in range(5):
            self.assertEqual(self.gate([PIVOT_F1], max_repairs=0, used=0).decision, 'pass', cycle)

    def test_a_genuinely_new_defect_in_the_same_file_and_criterion_still_blocks(self):
        decision = self.gate([PIVOT_F1, NEW_DEFECT], max_repairs=3, used=0)
        self.assertEqual(decision.decision, 'repair')
        self.assertEqual(decision.blocking, (NEW_DEFECT,))

    def test_a_ruling_is_scoped_to_its_task_files_and_reviewer(self):
        self.assertEqual(self.gate([PIVOT_F1], task='other-task').decision, 'human_review')
        self.assertEqual(self.gate([OTHER_FILE]).decision, 'human_review')
        other = evaluate_cycle(WRITER, [VERIFIER, result([PIVOT_F1.replace('claude-reviewer', 'codex-reviewer')], 'codex-reviewer')], None, 3, 3,
                               dict(task_id='scene-env-wiring', rulings=self.project['rulings']))
        self.assertEqual(other.decision, 'human_review')

    # material change
    def test_a_change_to_a_covered_or_watched_file_reopens_the_ruling(self):
        for changed in (META, 'Assets/Tests/Room01PresentationTests.cs'):
            with self.subTest(changed=changed):
                self.setUp()
                (self.dir / changed).write_text('v2')
                events = fr.refresh(self.project, self.dir, now=2)
                self.assertEqual(events[0]['changed'], [changed])
                self.assertEqual(self.project['rulings'][0]['state'], 'reopened')
                self.assertEqual(self.gate([PIVOT_F1]).decision, 'human_review')
                (self.dir / changed).write_text('v1 ' + changed)  # restoring the content does not silently revive it
                self.assertEqual(fr.refresh(self.project, self.dir), [])
                self.assertEqual(self.project['rulings'][0]['state'], 'reopened')

    def test_unchanged_files_keep_the_ruling_active(self):
        self.assertEqual(fr.refresh(self.project, self.dir), [])
        self.assertEqual(self.project['rulings'][0]['state'], 'active')

    # persistence and audit
    def test_rulings_survive_a_restart_as_plain_json(self):
        reloaded = json.loads(json.dumps(self.project))
        decision = evaluate_cycle(WRITER, [VERIFIER, result([PIVOT_F1])], None, 3, 3, dict(task_id='scene-env-wiring', rulings=reloaded['rulings']))
        self.assertEqual(decision.decision, 'pass')
        self.assertEqual(fr.refresh(reloaded, self.dir), [])

    def test_each_application_is_audited_once_per_task_and_cycle(self):
        decision = self.gate([PIVOT_F1])
        self.assertEqual(len(fr.record_applied(self.project, decision.waived, 'scene-env-wiring', 3)), 1)
        self.assertEqual(fr.record_applied(self.project, decision.waived, 'scene-env-wiring', 3), [])
        applied = self.project['rulings'][0]['applied'][0]
        self.assertEqual((applied['finding'], applied['cycle']), (PIVOT_F1, 3))

    def test_a_new_ruling_supersedes_the_older_one_and_keeps_it_in_history(self):
        newer = fr.normalize_rulings([ruling(reason='Re-decided after a second inspection of the importer data in the editor')], 'n', self.dir)
        fr.merge(self.project, newer)
        states = [r['state'] for r in self.project['rulings']]
        self.assertEqual(states, ['superseded', 'active'])

    def test_card_view_carries_evidence_for_the_task_only(self):
        shown = fr.card_view(self.project, 'scene-env-wiring')
        self.assertEqual(shown[0]['evidence'][0]['kind'], 'test')
        self.assertEqual(fr.card_view(self.project, 'other-task'), [])

    # validation
    def test_invalid_rulings_are_refused(self):
        bad = [dict(paths=['*']), dict(paths=['Assets/**/*.meta']), dict(paths=['missing.meta']), dict(paths=['../x']), dict(claim=[]),
               dict(evidence=[]), dict(verdict='maybe'), dict(reason='short'), dict(task='Bad Task'), dict(ac='all'), dict(extra=1)]
        for overrides in bad:
            with self.subTest(overrides=overrides), self.assertRaises(ConfigurationError):
                fr.normalize_rulings([ruling(**overrides)], 'n', self.dir)
        with self.assertRaises(ConfigurationError):
            normalize_decisions(dict(rulings=[ruling()]), '')  # a ruling needs a recorded note
        self.assertEqual(normalize_decisions(dict(rulings=[ruling()]), 'note')['rulings'][0]['task'], 'scene-env-wiring')


if __name__ == '__main__':
    unittest.main()
