import re
import unittest

import factory_copy as fc

FILES = {
    fc.DASHBOARD / 'factory_dashboard/assets/workflow_forms.js': "['feature','bug','chore','art','audio']",
    fc.DASHBOARD / 'factory_dashboard/assets/task_forms.js': "['feature','bug','chore','art','audio']",
    fc.SCRIPTS / 'factory_lib.py': '{"feature", "bug", "chore", "art", "audio"}',
    fc.SCRIPTS / 'factory_ticket.py': 'choices=["feature", "bug", "chore", "art", "audio"]',
    fc.SCRIPTS / 'factory_intake.py': '"art": "art", "audio": "audio"',
    fc.SCRIPTS / 'factory_publish.py': '"art": "feat(art)", "audio": "feat(audio)"',
}


class EnumerationTest(unittest.TestCase):
    def test_every_enumeration_has_audio(self):
        for path, needle in FILES.items():
            self.assertIn(needle, path.read_text(), path)

    def test_software_factory_skill_names_audio(self):
        text = (fc.SKILLS / 'orchestrator/software-factory/SKILL.md').read_text()
        self.assertRegex(text, r'art\|audio|art, audio|`audio`')

    def test_no_other_art_only_enumeration_left(self):
        for root in (fc.DASHBOARD / 'factory_dashboard', fc.SCRIPTS):
            for path in root.rglob('*'):
                if path.suffix in ('.py', '.js') and '__pycache__' not in path.parts and 'tests' not in path.parts:
                    for line in path.read_text(errors='replace').splitlines():
                        if re.search(r"""['"]chore['"]\s*,\s*['"]art['"]""", line):
                            self.assertIn('audio', line, f'{path}: {line.strip()}')


if __name__ == '__main__':
    unittest.main()
