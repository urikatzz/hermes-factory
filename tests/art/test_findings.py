import unittest

from factory_art.findings import finding, lines, ordered, override


class FindingTests(unittest.TestCase):
    def test_rejects_unknown_severity(self):
        with self.assertRaises(ValueError):
            finding('CRITICAL', 'size', 'a.png', 'x')

    def test_orders_by_severity_then_file_then_check(self):
        found = [finding('LOW', 'unsupported', 'b.jpg', 'x'), finding('HIGH', 'size', 'b.png', 'x'),
                 finding('HIGH', 'alpha', 'a.png', 'x'), finding('BLOCKER', 'unreadable', 'c.png', 'x')]
        self.assertEqual([(f['severity'], f['file']) for f in ordered(found)],
                         [('BLOCKER', 'c.png'), ('HIGH', 'a.png'), ('HIGH', 'b.png'), ('LOW', 'b.jpg')])

    def test_override_changes_only_named_checks(self):
        found = override([finding('HIGH', 'size', 'a.png', 'x'), finding('MEDIUM', 'palette', 'a.png', 'y')],
                         {'size': 'LOW'})
        self.assertEqual([f['severity'] for f in found], ['LOW', 'MEDIUM'])

    def test_lines_number_findings_and_escape_pipes(self):
        self.assertEqual(lines([finding('HIGH', 'size', 'a.png', '64|32')]), ['F1|HIGH|size|a.png|64/32'])
