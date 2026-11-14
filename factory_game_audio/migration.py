"""Game Audio roles, catalog entries, template and audio type default over factory_type_migration."""
from factory_type_migration import migration as _m
from factory_type_migration.migration import TypeSpec, write_receipt  # noqa: F401

NEW_ROLES = {
    'audio-director': {'provider': 'anthropic', 'model': 'claude-opus-5-5', 'effort': 'high'},
    'sound-designer': {'provider': 'openai-codex', 'model': 'gpt-6-luna', 'effort': 'medium'},
}
CHOICES_FROM = {'audio-director': 'architect', 'sound-designer': 'developer'}
SPEC = TypeSpec('audio', 'Game Audio', NEW_ROLES, CHOICES_FROM, 'factory-game-audio')


class Migration(_m.Migration):
    def __init__(self, dashboard_source, settings_db, catalog_path):
        super().__init__(SPEC, dashboard_source, settings_db, catalog_path)
