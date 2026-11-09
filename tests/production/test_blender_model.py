import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import PALETTE, gpl, write_glb
from factory_art.blender_runner import find_blender, render_model
from factory_art.model_checks import check_model
from factory_art.png import Image, write_png

CUBE_FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def run_model(*args, **env):
    return subprocess.run(['sh', str(ROOT / 'scripts/blender_run.sh'), *map(str, args)], capture_output=True,
                          text=True, env=dict(os.environ, **env), timeout=400)


class RunnerTests(unittest.TestCase):
    def test_usage_and_missing_blender(self):
        self.assertEqual(run_model('render', 'a.glb').returncode, 2)
        missing = run_model('cleanup', 'a.glb', 'b.glb', '--height', '1', BLENDER='/nonexistent/blender')
        self.assertEqual(missing.returncode, 4)
        self.assertIn('Blender not found', missing.stderr)


@unittest.skipUnless(find_blender(), 'Blender not installed: set BLENDER or install /Applications/Blender.app')
class BlenderModelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.env = {'BLENDER': find_blender()}

    def stats(self, glb):
        return render_model(find_blender(), glb, self.root / 'render' / glb.stem, 120)

    def offset_cube(self):
        """2 m tall cube floating 2 m up and 3 m to the side (glTF Y-up)."""
        source = self.root / 'offset.glb'
        positions = [(x + 3.0, y * 2.0 + 2.0, z) for x in (-0.5, 0.5) for y in (0.0, 1.0) for z in (-0.5, 0.5)]
        write_glb(source, positions, [i for a, b, c, d in CUBE_FACES for i in (a, b, c, a, c, d)])
        return source

    def test_cleanup_scales_to_height_with_a_bottom_centre_origin(self):
        out = self.root / 'clean.glb'
        result = run_model('cleanup', self.offset_cube(), out, '--height', '0.5', **self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['triangles'], 12)
        stats = self.stats(out)
        self.assertEqual(stats['triangles'], 12)
        self.assertAlmostEqual(stats['bbox_min'][2], 0.0, places=4)
        self.assertAlmostEqual(stats['bbox_max'][2], 0.5, places=4)
        self.assertAlmostEqual(stats['bbox_min'][0], -0.125, places=4)
        prop = {'triangles_max': 5000, 'height_m': [0.2, 2.0], 'origin': 'bottom_center'}
        self.assertEqual(check_model('clean.glb', stats, prop), [])

    def test_cleanup_with_a_centre_origin(self):
        out = self.root / 'centred.glb'
        result = run_model('cleanup', self.offset_cube(), out, '--height', '0.5', '--origin', 'center', **self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        stats = self.stats(out)
        self.assertAlmostEqual(stats['bbox_min'][2], -0.25, places=4)
        self.assertAlmostEqual(stats['bbox_max'][2], 0.25, places=4)

    def blockout(self, *extra):
        concept = self.root / 'concept.png'
        write_png(concept, Image(8, 8, [(255, 0, 0, 255)] * 32 + [(0, 0, 255, 255)] * 32))  # red top, blue bottom
        spec = self.root / 'parts.json'
        spec.write_text(json.dumps({'parts': [
            {'shape': 'cube', 'location': [0, 0, 0.5], 'size': [0.8, 0.6, 1.0], 'sample': [0.5, 0.75]},
            {'shape': 'sphere', 'location': [0, 0, 1.3], 'size': [0.6, 0.6, 0.6], 'sample': [0.5, 0.25]},
            {'shape': 'cone', 'location': [0, 0, 1.8], 'size': [0.3, 0.3, 0.4], 'rotation': [0, 0, 45],
             'colour': '#c83c3c'}]}))
        out = self.root / 'blockout.glb'
        return out, run_model('blockout', concept, out, '--height', '1.2', '--spec', spec, *extra, **self.env)

    def test_blockout_builds_coloured_primitives_from_the_spec(self):
        out, result = self.blockout()
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['colours'], ['#0000ff', '#ff0000', '#c83c3c'])
        self.assertEqual(data['parts'], 3)
        stats = self.stats(out)
        self.assertEqual(stats['materials'], 3)
        self.assertAlmostEqual(stats['bbox_min'][2], 0.0, places=4)
        self.assertAlmostEqual(stats['bbox_max'][2], 1.2, places=4)

    def test_blockout_snaps_colours_to_the_palette(self):
        (self.root / 'palette.gpl').write_text(gpl(PALETTE))
        out, result = self.blockout('--palette', self.root / 'palette.gpl')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['colours'], ['#3c78c8', '#c83c3c'])
        self.assertEqual(self.stats(out)['materials'], 2)

    def test_a_bad_spec_fails_with_a_reason(self):
        concept = self.root / 'concept.png'
        write_png(concept, Image(2, 2, [(255, 0, 0, 255)] * 4))
        spec = self.root / 'bad.json'
        spec.write_text(json.dumps({'parts': [{'shape': 'torus', 'location': [0, 0, 0], 'size': [1, 1, 1]}]}))
        result = run_model('blockout', concept, self.root / 'bad.glb', '--height', '1', '--spec', spec, **self.env)
        self.assertEqual(result.returncode, 1)
        self.assertIn('part shape must be one of', result.stderr)
        self.assertFalse((self.root / 'bad.glb').exists())
