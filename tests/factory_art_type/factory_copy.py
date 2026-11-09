"""Point imports at the Game Art build copy of the Factory, never at the live ~/.hermes install.

The copy defaults to artifacts/game-art-2026-10-26/build in this repo; set HERMES_GAME_ART_COPY to use another one. Run this suite in
its own process: tests/ecc imports the live factory_dashboard package.
"""
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
LIVE = Path.home() / '.hermes'
COPY = Path(os.environ.get('HERMES_GAME_ART_COPY', str(REPO / 'artifacts/game-art-2026-10-26/build'))).resolve()
DASHBOARD = COPY / 'factory-dashboard'
SCRIPTS = COPY / 'scripts'
SKILLS = COPY / 'factory-skills'

if COPY == LIVE.resolve() or LIVE.resolve() in COPY.parents:
    raise RuntimeError(f'{COPY} is inside the live Hermes home; use a copy')
if not (DASHBOARD / 'factory_dashboard' / 'workflow_types.py').is_file():
    raise RuntimeError(f'Factory copy missing at {COPY}: run the Task 7 copy commands first')
for path in (SCRIPTS / 'tests', SCRIPTS, DASHBOARD, REPO):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import factory_dashboard  # noqa: E402

if Path(factory_dashboard.__file__).resolve().parent != (DASHBOARD / 'factory_dashboard').resolve():
    raise RuntimeError(f'factory_dashboard was imported from {factory_dashboard.__file__}, not the copy')
