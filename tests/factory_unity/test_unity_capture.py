"""Unity scene capture: layout contract, completeness, verification of the engine's own account, orchestration (with a stand-in engine), and a real-engine regression."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from factory_art.png import Image, read_png, write_png
from factory_unity.layout import LayoutError, SCHEMA, completeness, validate_layout
from factory_unity.scene_capture import CaptureError, capture, project_version, unity_editor, verify_engine_capture

VERSION = '6000.4.11f1'


def solid(width, height, rgb):
    return Image(width, height, [rgb + (255,)] * (width * height))


def layout(**changes):
    base = dict(schema=SCHEMA, scene='Assets/Scenes/Test.unity', camera=dict(size=5, width=320, height=180),
                objects=[dict(id='wall', asset='Assets/Art/wall.png', position=[0, 0], size_units=[17.8], covers=['V1']),
                         dict(id='door', asset='Assets/Art/door.png', position=[-4, 0], size_units=[2], covers=['V2'])])
    base.update(changes)
    return base


class Project(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'game'
        (self.project / 'ProjectSettings').mkdir(parents=True); (self.project / 'ProjectSettings/ProjectVersion.txt').write_text(f'm_EditorVersion: {VERSION}\n')
        (self.project / 'Packages').mkdir(); (self.project / 'Packages/manifest.json').write_text('{"dependencies": {}}')
        (self.project / 'Assets/Art').mkdir(parents=True)
        write_png(self.project / 'Assets/Art/wall.png', solid(64, 36, (20, 20, 24)))
        write_png(self.project / 'Assets/Art/door.png', solid(32, 64, (200, 120, 20)))
        self.layout_path = self.root / 'layout.json'
        self.write_layout(layout())

    def write_layout(self, value):
        self.layout_path.write_text(json.dumps(value))
        return value


class LayoutTests(Project):
    def test_a_good_layout_validates_and_a_missing_asset_does_not(self):
        validate_layout(layout(), self.project)
        broken = layout(); broken['objects'][0]['asset'] = 'Assets/Art/nope.png'
        with self.assertRaises(LayoutError):
            validate_layout(broken, self.project)

    def test_unsafe_or_malformed_layouts_are_refused(self):
        bad = [layout(schema='x'), layout(scene='../escape.unity'), layout(scene='Assets/a.txt'), layout(camera=dict(size=5, width=10, height=10)), layout(camera=dict(size=0, width=320, height=180)),
               layout(objects=[]), layout(lighting='disco'), layout(objects=[dict(id='a', asset='../x.png')]), layout(objects=[dict(id='a', asset='/abs/x.png')]),
               layout(objects=[dict(id='a', asset='Assets/Art/wall.png'), dict(id='a', asset='Assets/Art/door.png')]),
               layout(objects=[dict(id='a', asset='Assets/Art/wall.png', covers=['not an id'])]), layout(objects=[dict(id='a', asset='Assets/Art/wall.png', position=[0, float('nan')])])]
        for item in bad:
            with self.subTest(item=str(item)[:70]):
                with self.assertRaises(LayoutError):
                    validate_layout(item, self.project)

    def test_completeness_names_the_required_elements_the_scene_does_not_cover(self):
        done = completeness(layout(), ['V1', 'V2', 'V3', 'V4'])
        self.assertEqual((done['present'], done['missing'], done['complete']), (['V1', 'V2'], ['V3', 'V4'], False))
        self.assertTrue(completeness(layout(), ['V1', 'V2'])['complete'])
        self.assertTrue(completeness(layout(), ['V1', 'V2', 'V3'], deferred=['V3'])['complete'])      # only a recorded deferral excludes an element
        self.assertEqual(completeness(layout(), ['V9'])['present'], [])                                 # coverage claimed for an id nobody requires is irrelevant


class StandInEngine:
    """Stands in for the Unity process in orchestration tests: writes what the real engine script writes, with switches to tamper with each claim."""

    def __init__(self, project, version=VERSION, **faults):
        self.project, self.version, self.faults, self.commands = project, version, faults, []

    def __call__(self, command, **kwargs):
        if command[0] == 'rsync' or command[0] == 'cp':
            return subprocess.run(command, **kwargs)
        self.commands.append(command)
        arg = lambda name: command[command.index(name) + 1]
        out, lay, log = Path(arg('-factoryOut')), json.loads(Path(arg('-factoryLayout')).read_text()), Path(arg('-logFile'))
        out.mkdir(parents=True, exist_ok=True)
        cam = lay['camera']
        shot = out / 'scene.png'
        write_png(shot, solid(cam['width'], cam['height'], (50, 60, 70)))
        scene = out / Path(lay['scene']).name
        scene.write_bytes(b'scene bytes')
        sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        renderers = [dict(object=o['id'], asset=o['asset'], guid='g', asset_sha256=sha(self.project / o['asset'])) for o in lay['objects']]
        engine = dict(schema='factory-engine-capture/v1', engine='Unity', engine_version=self.version, graphics_device='Apple M1 Max', graphics_api='Metal', platform='OSXEditor',
                      render_pipeline='UniversalRP', scene=lay['scene'], scene_sha256=sha(scene), layout_sha256=hashlib.sha256(Path(arg('-factoryLayout')).read_bytes()).hexdigest(),
                      screenshot='scene.png', screenshot_sha256=sha(shot), width=cam['width'], height=cam['height'], camera=dict(size=cam['size']), captured_at=1, renderers=renderers,
                      objects_placed=len(lay['objects']), lighting='unlit')
        for key, value in self.faults.items():
            if key == 'drop_renderer':
                engine['renderers'] = engine['renderers'][:-1]
            elif key == 'tamper_screenshot':
                shot.write_bytes(shot.read_bytes() + b'x')
            elif key == 'tamper_asset':
                engine['renderers'][0]['asset_sha256'] = '0' * 64
            else:
                engine[key] = value
        (out / 'engine-capture.json').write_text(json.dumps(engine))
        log.write_text('Unity log\nFactoryScene: captured %dx%d on Apple M1 Max\n' % (cam['width'], cam['height']))
        return subprocess.CompletedProcess(command, self.faults.get('exit', 0), '', '')


class CaptureOrchestrationTests(Project):
    def run_capture(self, **faults):
        engine = StandInEngine(self.project, **faults)
        editor = self.root / 'Unity'; editor.write_text('#!/bin/sh\n'); editor.chmod(0o755)
        record = capture(self.project, self.layout_path, self.root / 'out', ['V1', 'V2', 'V3'], editor=editor, run=engine)
        return record, engine

    def test_a_verified_capture_writes_the_render_record_the_scorer_and_controller_accept(self):
        record, engine = self.run_capture()
        self.assertEqual((record['schema'], record['width'], record['height'], record['exit_code']), ('factory-scene-render/v1', 320, 180, 0))
        self.assertEqual(record['screenshot_sha256'], hashlib.sha256((self.root / 'out/scene.png').read_bytes()).hexdigest())
        self.assertEqual(record['engine']['graphics_device'], 'Apple M1 Max'); self.assertTrue(record['isolated_clone'])
        self.assertEqual((record['completeness']['missing'], record['completeness']['complete']), (['V3'], False))   # V3 is required and nothing covers it: preliminary
        saved = json.loads((self.root / 'out/scene-render.json').read_text())
        self.assertEqual(saved['command'], engine.commands[0])
        from factory_art.scene_score import validate_render
        reference = self.root / 'ref.png'; write_png(reference, solid(320, 180, (1, 2, 3)))
        problems, _, _ = validate_render(saved, self.root / 'out/scene.png', reference, require_engine=True)
        self.assertEqual(problems, [])

    def test_the_project_is_never_modified_and_the_editor_script_goes_into_the_clone_only(self):
        before = {str(p.relative_to(self.project)): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        _, engine = self.run_capture()
        after = {str(p.relative_to(self.project)): p.read_bytes() for p in self.project.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertNotIn('-projectPath ' + str(self.project), ' '.join(engine.commands[0]))
        self.assertNotEqual(engine.commands[0][engine.commands[0].index('-projectPath') + 1], str(self.project))

    def assert_rejected(self, fragment, **faults):
        with self.assertRaises(CaptureError) as caught:
            self.run_capture(**faults)
        self.assertIn(fragment, str(caught.exception))
        self.assertFalse((self.root / 'out/scene-render.json').exists())     # a rejected capture leaves no record that could be scored

    def test_every_claim_of_the_engine_is_checked_against_the_files(self):
        self.assert_rejected('screenshot differs from the hash', tamper_screenshot=True)
        self.assert_rejected('different file than the project asset', tamper_asset=True)
        self.assert_rejected('did not render', drop_renderer=True)
        self.assert_rejected('not the project version', engine_version='2022.3.1f1')
        self.assert_rejected('no graphics device', graphics_device='')
        self.assert_rejected('different resolution', width=64)
        self.assert_rejected('different layout', layout_sha256='f' * 64)
        self.assert_rejected('saved scene does not match', scene_sha256='e' * 64)

    def test_a_failed_engine_run_is_not_a_capture(self):
        self.assert_rejected('Unity exited 3', exit=3)

    def test_a_missing_engine_or_a_bad_layout_or_project_is_reported_not_faked(self):
        with self.assertRaises(CaptureError) as caught:
            capture(self.project, self.layout_path, self.root / 'o2', editor=self.root / 'no-such-unity')
        self.assertEqual(caught.exception.stage, 'engine')
        self.write_layout(layout(objects=[]))
        with self.assertRaises(CaptureError) as caught:
            capture(self.project, self.layout_path, self.root / 'o3', editor=self.root / 'x')
        self.assertEqual(caught.exception.stage, 'layout')
        with self.assertRaises(CaptureError):
            project_version(self.root)

    def test_the_editor_is_looked_up_for_the_projects_unity_version(self):
        self.assertEqual(project_version(self.project), VERSION)
        fake = self.root / 'fake-unity'; fake.write_text('x')
        self.assertEqual(unity_editor(VERSION, {'FACTORY_UNITY_EDITOR': str(fake)}), fake)
        self.assertIsNone(unity_editor(VERSION, {'FACTORY_UNITY_EDITOR': str(self.root / 'absent')}))

    def test_verify_engine_capture_rejects_a_malformed_account(self):
        self.assertTrue(verify_engine_capture(None, self.root, layout(), 'x', self.project, VERSION))
        self.assertTrue(verify_engine_capture({'schema': 'nope'}, self.root, layout(), 'x', self.project, VERSION))


def installed_editor():
    return unity_editor('6000.4.11f1') or next((p for p in Path('/Applications/Unity/Hub/Editor').glob('*/Unity.app/Contents/MacOS/Unity')), None) if Path('/Applications/Unity/Hub/Editor').exists() else None


@unittest.skipUnless(os.environ.get('FACTORY_UNITY_REAL_TEST') == '1' and installed_editor(), 'set FACTORY_UNITY_REAL_TEST=1 with a Unity Editor installed to run the real-engine capture')
class RealEngineTests(Project):
    """The real Unity Editor renders a scene of two differently coloured sprites. The first version of the builder drew every sprite with the first sprite's texture."""

    def test_each_sprite_is_drawn_with_its_own_texture_by_the_real_engine(self):
        editor = installed_editor()
        version = editor.parents[3].name if 'Hub/Editor' in str(editor) else VERSION
        (self.project / 'ProjectSettings/ProjectVersion.txt').write_text(f'm_EditorVersion: {version}\n')
        write_png(self.project / 'Assets/Art/wall.png', solid(64, 36, (20, 200, 40)))     # green, large
        write_png(self.project / 'Assets/Art/door.png', solid(32, 64, (220, 30, 30)))     # red, small
        self.write_layout(layout(camera=dict(size=5, width=320, height=180, background=[0, 0, 1, 1]),
                                 objects=[dict(id='wall', asset='Assets/Art/wall.png', position=[0, 0], size_units=[17.8], sorting_order=0, covers=['V1']),
                                          dict(id='door', asset='Assets/Art/door.png', position=[-4, 0], size_units=[2], sorting_order=2, covers=['V2'])]))
        record = capture(self.project, self.layout_path, self.root / 'out', ['V1', 'V2'], editor=editor, timeout=1800)
        shot = read_png(self.root / 'out/scene.png')
        at = lambda x, y: shot.pixels[y * shot.width + x][:3]
        self.assertTrue(record['engine']['graphics_device'])
        per_unit = 180 / (2 * 5)                                                 # camera size 5 shows 10 units over 180 px
        green, red = at(250, 90), at(int(320 / 2 + (-4) * per_unit), 90)         # a point on the wall, and the centre of the door
        from collections import Counter
        colours = Counter(p[:3] for p in shot.pixels)
        self.assertEqual(set(colours), {(20, 200, 40), (220, 30, 30)})            # exactly the two textures, nothing else (no background, no stray sprite)
        self.assertGreater(green[1], 150); self.assertLess(green[0], 80)          # the wall is green
        self.assertGreater(red[0], 150); self.assertLess(red[1], 80)              # the door is red, not a copy of the wall's texture
        self.assertEqual(record['completeness']['complete'], True)


if __name__ == '__main__':
    unittest.main()
