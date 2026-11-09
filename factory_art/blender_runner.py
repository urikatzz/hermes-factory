"""Locate Blender and run the model render script with a timeout."""
import json
import os
from pathlib import Path
import shutil
import subprocess

DEFAULT_APP = '/Applications/Blender.app/Contents/MacOS/Blender'
SCRIPT = Path(__file__).parent / 'blender' / 'render_model.py'


class BlenderUnavailable(RuntimeError):
    pass


def find_blender(explicit=None):
    if explicit:
        return explicit if _executable(explicit) else None
    for candidate in (os.environ.get('BLENDER'), shutil.which('blender'), DEFAULT_APP):
        if candidate and _executable(candidate):
            return candidate
    return None


def render_model(blender, model, out, timeout=120):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name in ('stats.json', 'front.png', 'three_quarter.png', 'side.png', 'top.png'):
        (out / name).unlink(missing_ok=True)
    command = [blender, '-b', '--factory-startup', '--python-exit-code', '1', '-P', str(SCRIPT),
               '--', str(model), str(out)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise BlenderUnavailable(f'Blender timed out after {timeout}s') from error
    stats = out / 'stats.json'
    if not stats.is_file():
        raise BlenderUnavailable(f'Blender exited {completed.returncode} without stats: {completed.stderr[-300:]}')
    try:
        data = json.loads(stats.read_text())
    except ValueError as error:
        raise BlenderUnavailable(f'Blender wrote unreadable stats: {error}') from error
    if completed.returncode and not (isinstance(data, dict) and 'error' in data):
        raise BlenderUnavailable(f'Blender exited {completed.returncode}: {completed.stderr[-300:]}')
    return data


def _executable(path):
    return Path(path).is_file() and os.access(path, os.X_OK)
