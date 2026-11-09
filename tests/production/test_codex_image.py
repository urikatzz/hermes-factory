import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import sprite
from factory_art.png import read_png, write_png

STUB = f"""#!{sys.executable}
import json, os, pathlib, shutil, sys, time
args = sys.argv[1:]
pathlib.Path(os.environ['STUB_LOG']).write_text(json.dumps(args))
work = pathlib.Path(args[args.index('-C') + 1])
mode = os.environ['STUB_MODE']
if mode == 'copy':
    shutil.copy(os.environ['STUB_PNG'], work / 'image.png')
elif mode == 'home':
    target = pathlib.Path(os.environ['CODEX_HOME']) / 'generated_images' / 'thread-1'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(os.environ['STUB_PNG'], target / 'exec-new.png')
    print('Generated image saved to', target / 'exec-new.png')
elif mode == 'home-silent':
    target = pathlib.Path(os.environ['CODEX_HOME']) / 'generated_images' / 'thread-1'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy(os.environ['STUB_PNG'], target / 'exec-new.png')
elif mode == 'home-two':
    target = pathlib.Path(os.environ['CODEX_HOME']) / 'generated_images' / 'thread-1'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('exec-a.png', 'exec-b.png'):
        shutil.copy(os.environ['STUB_PNG'], target / name)
        print('Generated image saved to', target / name)
elif mode == 'race':
    time.sleep(float(os.environ['STUB_DELAY']))
    name = os.environ.get('STUB_NAME')
    if name:
        target = pathlib.Path(os.environ['CODEX_HOME']) / 'generated_images' / name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.environ['STUB_PNG'], target / 'exec.png')
        print('Generated image saved to', target / 'exec.png', flush=True)
        time.sleep(float(os.environ.get('STUB_LINGER', '0')))
elif mode == 'garbage':
    (work / 'image.png').write_bytes(b'not a png')
elif mode == 'sleep':
    time.sleep(60)
sys.exit(int(os.environ.get('STUB_EXIT', '0')))
"""


class CodexImageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.stub = self.root / 'codex'
        self.stub.write_text(STUB)
        self.stub.chmod(self.stub.stat().st_mode | stat.S_IXUSR)
        self.png = self.root / 'generated.png'
        write_png(self.png, sprite(32))
        self.prompt = self.root / 'prompt.txt'
        self.prompt.write_text('Use case: stylized-concept\nPrimary request: a red gem on a flat white background\n')
        self.out = self.root / 'art/concepts/gem.png'

    def run_script(self, mode, *args, **env):
        full = {k: v for k, v in os.environ.items() if k not in ('CODEX_HOME', 'HERMES_REAL_HOME')}
        full.update(CODEX_BIN=str(self.stub), CODEX_HOME=str(self.root / 'codex-home'), STUB_MODE=mode,
                    STUB_PNG=str(self.png), STUB_LOG=str(self.root / 'argv.json'))
        full.update(env)
        full = {k: v for k, v in full.items() if v is not None}
        args = args or (self.prompt, self.out)
        return subprocess.run(['sh', str(ROOT / 'scripts/codex_image.sh'), *map(str, args)],
                              capture_output=True, text=True, env=full, timeout=60)

    def argv(self):
        return json.loads((self.root / 'argv.json').read_text())

    def test_copies_the_generated_image_and_runs_codex_non_interactively(self):
        result = self.run_script('copy')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'width': 32, 'height': 32})
        self.assertEqual(read_png(self.out).pixels, sprite(32).pixels)
        argv = self.argv()
        self.assertEqual(argv[0], 'exec')
        for flag in ('--skip-git-repo-check', '--ephemeral', '--enable', 'image_generation', '-s', 'workspace-write'):
            self.assertIn(flag, argv)
        self.assertIn('a red gem on a flat white background', argv[-1])
        self.assertIn('image_gen', argv[-1])

    def test_falls_back_to_the_newest_image_codex_saved_after_the_start(self):
        old = self.root / 'codex-home/generated_images/old/exec-old.png'
        old.parent.mkdir(parents=True)
        write_png(old, sprite(16))
        os.utime(old, (time.time() - 3600, time.time() - 3600))
        result = self.run_script('home')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'width': 32, 'height': 32})

    def test_a_new_image_codex_did_not_mention_is_not_taken(self):
        result = self.run_script('home-silent')
        self.assertEqual(result.returncode, 1)
        self.assertIn('not referenced', result.stderr)
        self.assertFalse(self.out.exists())

    def test_two_new_images_are_ambiguous(self):
        result = self.run_script('home-two')
        self.assertEqual(result.returncode, 1)
        self.assertIn('2 new images', result.stderr)
        self.assertFalse(self.out.exists())

    def test_concurrent_runs_never_take_each_others_image(self):
        # Reviewer scenario: run A saves its image into the shared generated_images while run B (no image of its
        # own) is still running; B must fail instead of taking A's file.
        def start(name, delay, out, linger='0'):
            full = {k: v for k, v in os.environ.items() if k not in ('CODEX_HOME', 'HERMES_REAL_HOME')}
            full.update(CODEX_BIN=str(self.stub), CODEX_HOME=str(self.root / 'codex-home'), STUB_MODE='race',
                        STUB_PNG=str(self.png), STUB_LOG=str(self.root / f'argv-{name or "b"}.json'),
                        STUB_DELAY=delay, STUB_NAME=name, STUB_LINGER=linger)
            return subprocess.Popen(['sh', str(ROOT / 'scripts/codex_image.sh'), str(self.prompt), str(out)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=full)
        out_a, out_b = self.root / 'a.png', self.root / 'b.png'
        run_a = start('thread-a', '0.5', out_a, linger='2')
        run_b = start('', '1.5', out_b)
        _, err_b = run_b.communicate(timeout=60)
        run_a.communicate(timeout=60)
        self.assertEqual(run_a.returncode, 0)
        self.assertTrue(out_a.is_file())
        self.assertEqual(run_b.returncode, 1, err_b)
        self.assertFalse(out_b.exists())

    def test_codex_home_defaults_to_the_real_home_under_hermes(self):
        real = self.root / 'real-home'
        result = self.run_script('home', CODEX_HOME=None, HERMES_REAL_HOME=str(real))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((real / '.codex/generated_images/thread-1/exec-new.png').is_file())

    def test_undecodable_or_missing_images_fail_without_writing_out(self):
        for mode in ('garbage', 'none', 'home-silent'):
            result = self.run_script(mode)
            self.assertEqual(result.returncode, 1, mode)
            self.assertFalse(self.out.exists(), mode)

    def test_timeout_stops_codex(self):
        started = time.time()
        result = self.run_script('sleep', CODEX_IMAGE_TIMEOUT='2')
        self.assertEqual(result.returncode, 1)
        self.assertIn('timed out after 2s', result.stderr)
        self.assertLess(time.time() - started, 30)

    def test_usage_and_missing_codex(self):
        self.assertEqual(self.run_script('copy', self.prompt).returncode, 2)
        self.assertEqual(self.run_script('copy', self.prompt, self.root / 'gem.jpg').returncode, 2)
        self.assertEqual(self.run_script('copy', CODEX_BIN=str(self.root / 'missing')).returncode, 4)
