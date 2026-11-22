"""Assemble a real Unity scene from a layout and capture it with the engine. Reusable: it knows no game, only a project directory and a factory-scene-layout/v1 file.

The project is never touched. It is cloned (sources and settings, with the Library cache cloned copy-on-write so the import is incremental) into a scratch directory, the
factory's editor script is installed in the clone only, and Unity runs in batch mode there. That also works while a person has the same project open in the Editor,
which holds the project lock. The engine then states what it rendered (engine-capture.json); `verify_engine_capture` cross-checks every claim against the files, and
only a verified capture is written as the `factory-scene-render/v1` record the scorer and the controller accept."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

from factory_unity.layout import LayoutError, completeness, load_layout

RENDER_SCHEMA = 'factory-scene-render/v1'
ENGINE_SCHEMA = 'factory-engine-capture/v1'
EDITOR_SCRIPT = Path(__file__).parent / 'editor' / 'FactorySceneBuilder.cs'
EXCLUDE = ('Library/', 'Temp/', 'Logs/', 'UserSettings/', 'obj/', 'Builds/', '.git', '.worktrees/', '.factory/', '*.csproj', '*.sln', '.vs/', '.idea/')
ENGINE_KEYS = {'schema', 'engine', 'engine_version', 'graphics_device', 'graphics_api', 'platform', 'render_pipeline', 'scene', 'scene_sha256', 'layout_sha256', 'screenshot',
               'screenshot_sha256', 'width', 'height', 'camera', 'captured_at', 'renderers', 'objects_placed', 'lighting'}


class CaptureError(Exception):
    """The scene could not be captured or the engine's account of the capture does not check out. Never a score, never a pass."""

    def __init__(self, message, stage='capture'):
        super().__init__(message)
        self.stage = stage


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project_version(project):
    try:
        text = (Path(project) / 'ProjectSettings/ProjectVersion.txt').read_text()
        return re.search(r'm_EditorVersion:\s*(\S+)', text).group(1)
    except (OSError, AttributeError) as error:
        raise CaptureError('not a Unity project: ProjectSettings/ProjectVersion.txt is missing', 'project') from error


def unity_editor(version, environ=os.environ):
    """The Editor binary for this project's Unity version: FACTORY_UNITY_EDITOR, or the Hub's install location."""
    explicit = environ.get('FACTORY_UNITY_EDITOR')
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    system = platform.system()
    candidates = {'Darwin': [f'/Applications/Unity/Hub/Editor/{version}/Unity.app/Contents/MacOS/Unity'],
                  'Linux': [str(Path.home() / f'Unity/Hub/Editor/{version}/Editor/Unity'), f'/opt/unity/{version}/Editor/Unity'],
                  'Windows': [f'C:/Program Files/Unity/Hub/Editor/{version}/Editor/Unity.exe']}.get(system, [])
    return next((Path(c) for c in candidates if Path(c).is_file()), None)


def library_source(project):
    """A Library cache to clone from: the project's own, else the main worktree's when this project is a git worktree."""
    own = Path(project) / 'Library'
    if own.is_dir():
        return own
    try:
        common = subprocess.run(['git', '-C', str(project), 'rev-parse', '--git-common-dir'], capture_output=True, text=True, timeout=20).stdout.strip()
        main = (Path(project) / common).resolve().parent
        return main / 'Library' if (main / 'Library').is_dir() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def prepare_clone(project, scratch, library_from=None, run=subprocess.run):
    """Copy the project's sources and settings into scratch/project (never the project itself), clone the Library cache when one exists."""
    clone = Path(scratch) / 'project'
    clone.mkdir(parents=True, exist_ok=True)
    args = ['rsync', '-a', '--delete'] + [f'--exclude={e}' for e in EXCLUDE] + [str(project).rstrip('/') + '/', str(clone) + '/']
    done = run(args, capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        raise CaptureError('could not clone the project: ' + (done.stderr or '')[-300:], 'clone')
    source = library_from or library_source(project)
    if source and Path(source).is_dir() and not (clone / 'Library').exists():
        cloned = run(['cp', '-cR', str(source), str(clone / 'Library')], capture_output=True, text=True, timeout=1800)
        if cloned.returncode != 0:                       # not APFS: a plain copy is slower but equivalent
            shutil.copytree(source, clone / 'Library', symlinks=True, ignore_dangling_symlinks=True)
    (clone / 'Library' / 'EditorInstance.json').unlink(missing_ok=True)   # the cloned Library names the source project's running Editor; the clone is not open anywhere
    target = clone / 'Assets/Editor/FactoryScene'
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EDITOR_SCRIPT, target / EDITOR_SCRIPT.name)
    return clone


def verify_engine_capture(engine, out_dir, layout, layout_sha, project, expected_version, log_text=''):
    """Every claim of engine-capture.json checked against the files. Returns the list of problems (empty = the capture is a verified engine render)."""
    problems = []
    if not isinstance(engine, dict) or not ENGINE_KEYS <= set(engine) or engine.get('schema') != ENGINE_SCHEMA:
        return ['engine-capture.json is missing or malformed']
    if engine['engine'] != 'Unity' or engine['engine_version'] != expected_version:
        problems.append(f'engine version {engine.get("engine_version")!r} is not the project version {expected_version!r}')
    if not isinstance(engine['graphics_device'], str) or not engine['graphics_device'].strip():
        problems.append('the engine reported no graphics device (no real render happened)')
    shot = Path(out_dir) / str(engine['screenshot'])
    if not shot.is_file() or not shot.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        problems.append('the screenshot is missing or not a PNG')
    elif sha256_file(shot) != engine['screenshot_sha256']:
        problems.append('the screenshot differs from the hash the engine computed')
    cam = layout['camera']
    if (engine['width'], engine['height']) != (cam['width'], cam['height']):
        problems.append('the engine rendered a different resolution than the layout asked for')
    scene_copy = Path(out_dir) / Path(layout['scene']).name
    if not scene_copy.is_file() or sha256_file(scene_copy) != engine['scene_sha256']:
        problems.append('the saved scene does not match the scene the engine rendered')
    if engine['layout_sha256'] != layout_sha:
        problems.append('the engine built a different layout than the one given')
    rendered = {r.get('asset'): r for r in engine['renderers'] if isinstance(r, dict)}
    if engine['objects_placed'] != len(layout['objects']) or len(engine['renderers']) != len(layout['objects']):
        problems.append('the engine placed a different number of objects than the layout lists')
    for item in layout['objects']:
        record = rendered.get(item['asset'])
        real = Path(project) / item['asset']
        if record is None:
            problems.append('the engine did not render ' + item['asset'])
        elif real.is_file() and record.get('asset_sha256') != sha256_file(real):
            problems.append('the engine rendered a different file than the project asset ' + item['asset'])
    if log_text and 'FactoryScene: captured' not in log_text:
        problems.append('the Unity log has no capture confirmation')
    return problems


def capture(project, layout_path, out_dir, required=(), deferred=(), editor=None, timeout=3600, run=subprocess.run, library_from=None, keep_scratch=False):
    """Build and capture. Returns the scene-render record (also written to out_dir/scene-render.json). Raises CaptureError; never fabricates."""
    project, out_dir = Path(project).resolve(), Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        layout, layout_sha = load_layout(layout_path, project)
    except LayoutError as error:
        raise CaptureError(str(error), 'layout') from error
    version = project_version(project)
    binary = Path(editor) if editor else unity_editor(version)
    if binary is None or not Path(binary).is_file():
        raise CaptureError(f'Unity {version} is not installed (set FACTORY_UNITY_EDITOR): no engine, no capture', 'engine')
    scratch = out_dir / '.capture-scratch'
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        clone = prepare_clone(project, scratch, library_from, run)
        layout_in_clone = scratch / 'layout.json'
        shutil.copy2(layout_path, layout_in_clone)
        engine_dir, log = out_dir / 'engine', out_dir / 'unity.log'
        shutil.rmtree(engine_dir, ignore_errors=True)
        command = [str(binary), '-batchmode', '-quit', '-projectPath', str(clone), '-executeMethod', 'FactoryScene.BuildAndCapture',
                   '-factoryLayout', str(layout_in_clone), '-factoryOut', str(engine_dir), '-logFile', str(log)]
        started = time.time()
        done = run(command, capture_output=True, text=True, timeout=timeout)
        log_text = log.read_text(errors='replace') if log.is_file() else ''
        if done.returncode != 0:
            lines = log_text.splitlines()
            own = [l for l in lines if 'FactoryScene failed' in l or 'error CS' in l or 'Exception:' in l]
            noise = [l for l in lines if 'error' in l.lower() and 'Licensing' not in l]
            raise CaptureError(f'Unity exited {done.returncode}: ' + ' | '.join((own or noise)[:4])[-600:], 'engine')
        try:
            engine = json.loads((engine_dir / 'engine-capture.json').read_text())
        except (OSError, ValueError):
            engine = None
        problems = verify_engine_capture(engine, engine_dir, layout, layout_sha, project, version, log_text)
        if problems:
            raise CaptureError('engine capture rejected: ' + '; '.join(problems), 'verify')
        shot = out_dir / 'scene.png'
        shutil.copy2(engine_dir / 'scene.png', shot)
        shutil.copy2(engine_dir / Path(layout['scene']).name, out_dir / Path(layout['scene']).name)
        shutil.copy2(engine_dir / 'engine-capture.json', out_dir / 'engine-capture.json')
        record = dict(schema=RENDER_SCHEMA, renderer='unity-' + engine['render_pipeline'].replace(' ', '-').lower(), command=command, exit_code=done.returncode,
                      scene=layout['scene'], project_dir=str(project), screenshot='scene.png', screenshot_sha256=sha256_file(shot), width=engine['width'], height=engine['height'],
                      captured_at=engine['captured_at'], engine=engine, layout_sha256=layout_sha, completeness=completeness(layout, required, deferred),
                      isolated_clone=True, duration_seconds=round(time.time() - started, 1))
        (out_dir / 'scene-render.json').write_text(json.dumps(record, indent=2) + '\n')
        return record
    finally:
        if not keep_scratch:
            shutil.rmtree(scratch, ignore_errors=True)
