#!/usr/bin/env python3
"""Read-only check of an installed Game Art rollout. Never launches a worker and never writes to the Hermes home.

Imports the installed plugin bundle, captures an Art task on a private sqlite .backup copy of the settings store,
builds every stage card for it, and checks catalog, profiles, plugin copies, roster and skills. Exit 1 on problems.
"""
import argparse
import filecmp
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

ART_PROFILES = ('art-director', 'artist', 'art-reviewer')
STAGES = {'prepare': ('art-director', 'scratch'), 'implement': ('artist', 'dir'), 'repair': ('artist', 'dir'),
          'art-reviewer': ('art-reviewer', 'scratch'), 'claude-reviewer': ('claude-reviewer', 'scratch'),
          'verify': ('verifier', 'scratch')}


def config_model(text):
    lines = text.splitlines()
    start = lines.index('model:')
    values = dict(line.strip().split(': ', 1) for line in lines[start + 1:start + 3])
    return values.get('provider'), values.get('default')


def roster(text):
    lines, names, inside = text.splitlines(), [], False
    for line in lines:
        if line.strip() == 'dispatch_profiles:':
            inside = True
        elif inside and line.strip().startswith('- '):
            names.append(line.strip()[2:])
        elif inside and line.strip() and not line.strip().startswith('#'):
            break
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-home', type=Path, default=Path.home() / '.hermes')
    home = parser.parse_args().hermes_home.resolve()
    bundle = home / 'plugins/factory-models'
    sys.path.insert(0, str(bundle))
    from factory_dashboard.model_catalog import ModelCatalog
    from factory_dashboard.model_policy import ModelSelection
    from factory_dashboard.task_settings_store import TaskSettingsStore
    from factory_dashboard.workflow_capture import WorkflowCapture
    from factory_dashboard.workflow_cards import build_stage_card
    from factory_dashboard.workflow_types import CAPABILITIES, TASK_TYPES
    problems, cards = [], {}
    if 'art' not in TASK_TYPES or not set(ART_PROFILES) <= set(CAPABILITIES):
        problems.append('installed plugin bundle lacks the art type or profiles')
    catalog = ModelCatalog.from_file(home / 'state/factory/model-catalog.json')
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / 'settings.db'
        source = sqlite3.connect(f"file:{home / 'state/factory/task-settings.db'}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        source.backup(target)
        target.close()
        source.close()
        store = TaskSettingsStore(copy, create=False)
        roles = store.read_defaults().roles
        for role, settings in roles.items():
            try:
                catalog.validate(ModelSelection(settings.provider, settings.model), (role,))
            except ValueError as error:
                problems.append(f'{role}: {error}')
        for role in ART_PROFILES:
            if role not in roles:
                problems.append(f'{role} has no Factory default')
            elif roles[role].provider not in ('anthropic', 'openai-codex', 'openrouter'):
                problems.append(f'{role} default provider {roles[role].provider} is not allowed')
        with store._connect() as conn:
            if not WorkflowCapture.enabled(conn):
                problems.append('workflow capture is disabled in the settings store')
                conn.execute('UPDATE factory_workflow_activation SET enabled=1 WHERE id=1')  # private copy only
        try:
            workflow = store.get_snapshot(store.capture_task(
                'game-art-check', 't_gameartcheck', 'direct_root', workflow_selection={'type': 'art'})).workflow
        except ValueError as error:
            problems.append(f'an art task cannot be captured: {error}')
            workflow = None
        if workflow is not None and workflow.name != 'Game Art':
            problems.append(f'an art task captured {workflow.name}, not Game Art')
        elif workflow is not None:
            for key, (profile, workspace) in STAGES.items():
                card = build_stage_card(workflow, key, 0, {'project_dir': '/tmp/game-art-check', 'root_id': 't_gameartcheck'}, [])
                cards[key] = {'assignee': card['assignee'], 'workspace': card['workspace_kind'], 'skills': card['skills']}
                if (card['assignee'], card['workspace_kind'], card['skills']) != (profile, workspace, ['factory-worker']):
                    problems.append(f'{key} card is {cards[key]}')
    homes = [home] + sorted(path for path in (home / 'profiles').iterdir() if (path / 'plugins/factory-models').is_dir())
    for other in homes[1:]:
        if not filecmp.cmp(other / 'plugins/factory-models/factory_dashboard/workflow_types.py',
                           bundle / 'factory_dashboard/workflow_types.py', shallow=False):
            problems.append(f'{other.name}: plugin bundle differs from the root bundle')
    for profile in ART_PROFILES:
        folder = home / 'profiles' / profile
        if not (folder / 'config.yaml').is_file():
            problems.append(f'profile {profile} is missing')
            continue
        text = (folder / 'config.yaml').read_text()
        provider, model = config_model(text)
        if provider not in ('anthropic', 'openai-codex', 'openrouter'):
            problems.append(f'profile {profile} uses provider {provider}')
        if '    - vision' not in text:
            problems.append(f'profile {profile} lacks the vision toolset')
        if 'dispatch_in_gateway: false' not in text:
            problems.append(f'profile {profile} must keep dispatch_in_gateway: false')
        if not (folder / 'plugins/factory-models').is_dir():
            problems.append(f'profile {profile} lacks the factory-models plugin')
        if not (folder / 'SOUL.md').read_text().strip():
            problems.append(f'profile {profile} has an empty SOUL.md')
    missing = set(ART_PROFILES) - set(roster((home / 'config.yaml').read_text()))
    if missing:
        problems.append(f'root kanban.dispatch_profiles lacks {sorted(missing)}')
    skills = home / 'factory-skills/worker'
    if not (skills / 'art-production/SKILL.md').is_file():
        problems.append('art-production skill is not installed')
    if '--fail-on-blocking' not in (skills / 'art-review/scripts/art_lint.py').read_text():
        problems.append('installed art_lint.py lacks --fail-on-blocking')
    print(json.dumps({'ok': not problems, 'problems': problems, 'cards': cards}, indent=2))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
