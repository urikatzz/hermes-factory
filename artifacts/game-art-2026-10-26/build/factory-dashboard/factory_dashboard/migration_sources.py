"""Read-only migration inputs from the installed board, profiles and staged policy."""
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote
from .factory_model_resolver import board_key
from .model_catalog import ModelCatalog
from .policy_store import PolicyStore
from .settings_migration import SettingsMigration
from .task_settings_store import TaskSettingsStore


def migration_for(board_path, board_id, hermes_home, catalog_path, settings_path, old_policy_path):
    import yaml
    identity = board_key(board_path, board_id)
    catalog = ModelCatalog.from_file(catalog_path)
    def board():
        with closing(sqlite3.connect('file:' + quote(str(Path(board_path).resolve())) + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute('SELECT * FROM tasks')]
    def profiles():
        result = {}
        for role in catalog.defaults():
            config = yaml.safe_load((Path(hermes_home) / 'profiles' / role / 'config.yaml').read_text())
            result[role] = {'provider': config['model']['provider'], 'model': config['model']['default'],
                            'effort': config.get('agent', {}).get('reasoning_effort')}
        return result
    def overrides():
        if not old_policy_path or not Path(old_policy_path).exists():
            return {}
        policy = PolicyStore(old_policy_path, create=False).read()
        return {tid: asdict(value) for (board, tid), value in policy.overrides.items() if board == identity}
    return SettingsMigration(TaskSettingsStore(settings_path), identity, board, profiles, overrides)
