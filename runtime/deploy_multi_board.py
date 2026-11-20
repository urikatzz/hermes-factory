#!/usr/bin/env python3
"""Sync the multi-board Factory from tracked source into the live Hermes home. Dormant by design: it restarts nothing.

Each file is replaced atomically (copy to a temp name, then rename), new modules before the modules that import them and the plugin
entry point last, so a worker process that starts mid-sync always sees a consistent plugin. The previous file is kept as
`<name>.pre-multi-board` unless it already exists. Run with --dry-run first.
"""
import argparse
import os
from pathlib import Path
import shutil

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / 'runtime'
DASH = RUNTIME / 'factory-dashboard'
HOME = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')

PLUGIN_MODULES = ['board_registry.py', 'run_boards.py', 'factory_creation.py', 'task_settings_store.py', 'hermes_compat.py']
DASH_MODULES = PLUGIN_MODULES + ['runs_service.py', 'runs_http.py', 'http_server.py']
DASH_ASSETS = ['live.html', 'runs.html', 'runs.js']
DASH_SCRIPTS = ['factory_boards.py', 'resume_factory_workflow.py', 'serve_factory_dashboard.py', 'bundle_factory_plugin.py']
CRON = ['factory_lib.py', 'factory_intake.py', 'factory_alerts.py', 'factory_publish.py', 'factory_watchdog.py', 'factory_resume_rate_limit.py', 'factory_status.py', 'factory_patch_check.py']
CRON_TESTS = ['sandbox.py', 'test_boards.py']


def put(src, dst, dry):
    dst = Path(dst)
    print(('would copy ' if dry else 'copy ') + str(src.relative_to(REPO)) + ' -> ' + str(dst))
    if dry:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    keep = dst.with_name(dst.name + '.pre-multi-board')
    if dst.exists() and not keep.exists():
        shutil.copy2(dst, keep)
    tmp = dst.with_name('.' + dst.name + '.new')
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    dry = parser.parse_args().dry_run
    plugins = [HOME / 'plugins' / 'factory-models', *sorted((HOME / 'profiles').glob('*/plugins/factory-models'))]
    for plugin in plugins:
        for name in PLUGIN_MODULES:
            put(DASH / 'factory_dashboard' / name, plugin / 'factory_dashboard' / name, dry)
        put(DASH / 'integrations/hermes_factory_models/__init__.py', plugin / '__init__.py', dry)  # last: it imports the modules above
    app = HOME / 'factory-dashboard'
    for name in DASH_MODULES:
        put(DASH / 'factory_dashboard' / name, app / 'factory_dashboard' / name, dry)
    for name in DASH_ASSETS:
        put(DASH / 'factory_dashboard/assets' / name, app / 'factory_dashboard/assets' / name, dry)
    for name in DASH_SCRIPTS:
        put(DASH / 'scripts' / name, app / 'scripts' / name, dry)
    put(DASH / 'integrations/hermes_factory_models/__init__.py', app / 'integrations/hermes_factory_models/__init__.py', dry)
    for name in CRON:
        put(RUNTIME / 'factory-scripts' / name, HOME / 'scripts' / name, dry)
    for name in CRON_TESTS:
        put(RUNTIME / 'factory-scripts/tests' / name, HOME / 'scripts/tests' / name, dry)
    kanban = HOME / 'hermes-agent/plugins/kanban/dashboard'
    put(RUNTIME / 'kanban-plugin/plugin_api.py', kanban / 'plugin_api.py', dry)
    put(RUNTIME / 'kanban-plugin/index.js', kanban / 'dist/index.js', dry)


if __name__ == '__main__':
    main()
