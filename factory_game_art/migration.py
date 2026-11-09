"""Game Art spec over the generic type migration. Public names kept for scripts/migrate_game_art.py and its tests."""
from factory_type_migration.migration import (ALLOWED_PROVIDERS, TypeSpec, profiles, write_atomic, write_receipt)  # noqa: F401
from factory_type_migration import migration as _m

NEW_ROLES = {
    'art-director': {'provider': 'anthropic', 'model': 'claude-opus-5-5', 'effort': 'high'},
    'artist': {'provider': 'openai-codex', 'model': 'gpt-6-luna', 'effort': 'medium'},
    'art-reviewer': {'provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'effort': 'high'},
}
CHOICES_FROM = {'art-director': 'architect', 'artist': 'developer', 'art-reviewer': 'verifier'}
TEMPLATE_NAME = 'Game Art'
SPEC = TypeSpec('art', TEMPLATE_NAME, NEW_ROLES, CHOICES_FROM, 'factory-game-art')


def load_source(dashboard_source):
    return _m.load_source(dashboard_source, SPEC)


def catalog_changes(catalog):
    return _m.catalog_changes(catalog, SPEC)


class Migration(_m.Migration):
    def __init__(self, dashboard_source, settings_db, catalog_path):
        super().__init__(SPEC, dashboard_source, settings_db, catalog_path)
