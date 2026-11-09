import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import sprite
from factory_art.png import write_png


class InstallTests(unittest.TestCase):
    def test_installs_a_runnable_skill_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / 'skills'
            env = dict(os.environ, HERMES_FACTORY_SKILLS=str(skills))
            command = ['sh', str(ROOT / 'scripts/install_art_production.sh')]
            first = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            skill = skills / 'art-production'
            text = (skill / 'SKILL.md').read_text()
            self.assertTrue(text.startswith('---\nname: art-production\n'))
            self.assertIn(f'sh {skill}/scripts/codex_image.sh', text)
            self.assertIn(f'python3 {skills}/art-review/scripts/art_lint.py', text)
            for path in [skill / 'SKILL.md', *(skill / 'souls').glob('*.md')]:
                self.assertNotIn('${', path.read_text(), path)
            self.assertEqual(sorted(p.name for p in (skill / 'souls').iterdir()),
                             ['art-director.SOUL.md', 'artist.SOUL.md'])
            self.assertFalse(list(skill.rglob('__pycache__')))
            self.assertFalse((skill / 'art_production/install').exists())
            for name in ('sprite_fit.py', 'check_png.py', 'tripo_model.py', 'codex_image.sh', 'blender_run.sh'):
                self.assertTrue(os.access(skill / 'scripts' / name, os.X_OK), name)
            self.assertTrue((skill / 'scripts/blender_model.py').is_file())
            write_png(Path(temp) / 'in.png', sprite(32))
            fit = subprocess.run([sys.executable, str(skill / 'scripts/sprite_fit.py'), str(Path(temp) / 'in.png'),
                                  str(Path(temp) / 'out.png'), '--size', '16x16'], capture_output=True, text=True)
            self.assertEqual(fit.returncode, 0, fit.stderr)
            env_no_key = {k: v for k, v in os.environ.items() if k != 'TRIPO_API_KEY'}
            tripo = subprocess.run([sys.executable, str(skill / 'scripts/tripo_model.py'), str(Path(temp) / 'in.png'),
                                    str(Path(temp) / 'm.glb')], capture_output=True, text=True, env=env_no_key)
            self.assertEqual(tripo.returncode, 3, tripo.stderr)
            self.assertIn('TRIPO_API_KEY', json.loads(tripo.stdout)['fallback'])
            again = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(again.returncode, 1)
            self.assertIn('already exists', again.stderr)


class SoulTextTests(unittest.TestCase):
    SOULS = ROOT / 'art_production/install'

    def test_artist_soul_has_the_writer_start_of_stage_checks(self):
        soul = (self.SOULS / 'artist.SOUL.md').read_text()
        for text in ('.factory/ROOT', 'PROJECT_MODE=new', '`$HERMES_KANBAN_WORKSPACE` differs from the card\'s PROJECT_DIR',
                     'fw.py check PROJECT_DIR --expect <BASELINE>', 'at most 2 files per command', 'plain `rm <file>`'):
            self.assertIn(text, soul)

    def test_art_director_records_the_style_hash(self):
        soul = (self.SOULS / 'art-director.SOUL.md').read_text()
        self.assertIn('--style-hash', soul)
        self.assertIn('style_sha256', soul)
