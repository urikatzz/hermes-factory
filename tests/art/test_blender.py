import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from art_fixtures import cube, grid
from factory_art.blender_runner import BlenderUnavailable, find_blender, render_model
from factory_art.model_checks import check_model
from factory_art.views import contact_sheet

FAKE = f"""#!{sys.executable}
import json, pathlib, sys, time
model, out = sys.argv[sys.argv.index('--') + 1:]
mode = pathlib.Path(model).read_text()
if mode == 'sleep':
    time.sleep(5)
elif mode == 'stats':
    (pathlib.Path(out) / 'stats.json').write_text(json.dumps({{'triangles': 12}}))
elif mode == 'error':
    (pathlib.Path(out) / 'stats.json').write_text(json.dumps({{'error': 'bad model'}}))
elif mode == 'garbage':
    (pathlib.Path(out) / 'stats.json').write_text('{{')
    sys.exit(0)
sys.exit(1)
"""


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fake = self.root / 'blender'
        self.fake.write_text(FAKE)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.temp.cleanup()

    def run_fake(self, mode, timeout=30):
        model = self.root / 'model.glb'
        model.write_text(mode)
        return render_model(str(self.fake), model, self.root / 'out', timeout)

    def test_find_blender_order(self):
        self.assertIsNone(find_blender('/nonexistent/blender'))
        self.assertEqual(find_blender(str(self.fake)), str(self.fake))
        with mock.patch.dict(os.environ, {'BLENDER': str(self.fake)}):
            self.assertEqual(find_blender(), str(self.fake))

    def test_error_stats_survive_nonzero_exit_but_plain_stats_do_not(self):
        self.assertEqual(self.run_fake('error'), {'error': 'bad model'})
        with self.assertRaisesRegex(BlenderUnavailable, 'exited 1'):
            self.run_fake('stats')

    def test_stale_outputs_are_removed_before_running(self):
        out = self.root / 'out'
        out.mkdir()
        (out / 'stats.json').write_text('{"triangles": 1}')
        (out / 'front.png').write_text('old')
        with self.assertRaisesRegex(BlenderUnavailable, 'without stats'):
            self.run_fake('crash')
        self.assertFalse((out / 'front.png').exists())

    def test_unparseable_stats_is_environment_failure(self):
        with self.assertRaisesRegex(BlenderUnavailable, 'unreadable stats'):
            self.run_fake('garbage')

    def test_missing_stats_and_timeout_are_environment_failures(self):
        with self.assertRaisesRegex(BlenderUnavailable, 'without stats'):
            self.run_fake('crash')
        with self.assertRaisesRegex(BlenderUnavailable, 'timed out after 1s'):
            self.run_fake('sleep', timeout=1)


@unittest.skipUnless(find_blender(), 'Blender not installed: set BLENDER or install /Applications/Blender.app')
class RealBlenderTests(unittest.TestCase):
    def test_cube_and_dense_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cube(root / 'crate.glb')
            grid(root / 'dense.glb')
            stats = render_model(find_blender(), root / 'crate.glb', root / 'crate', 120)
            self.assertEqual(stats['triangles'], 12)
            self.assertEqual(stats['materials'], 0)
            self.assertEqual(stats['textures'], [])
            self.assertAlmostEqual(stats['bbox_min'][2], 0.0, places=4)
            self.assertAlmostEqual(stats['bbox_max'][2], 1.0, places=4)
            views = [root / 'crate' / f'{view}.png' for view in ('front', 'three_quarter', 'side', 'top')]
            self.assertTrue(all(view.is_file() for view in views))
            contact_sheet(views, root / 'crate' / 'contact.png')   # Blender PNGs decode with factory_art.png
            prop = {'triangles_max': 5000, 'height_m': [0.2, 2.0], 'origin': 'bottom_center'}
            self.assertEqual(check_model('crate.glb', stats, prop), [])
            dense = render_model(find_blender(), root / 'dense.glb', root / 'dense', 120)
            self.assertEqual(dense['triangles'], 7200)
            self.assertIn('triangles', [f['check'] for f in check_model('dense.glb', dense, prop)])
