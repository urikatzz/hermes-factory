"""Credential-free catalog, explicitly scoped to each Factory worker profile."""
import json
from pathlib import Path

from .model_policy import ConfigurationError, ModelSelection, identifier


class ModelCatalog:
    def __init__(self, data: dict):
        self._source = None
        self._load(data)

    def _load(self, data: dict):
        self._profiles = {}
        self._defaults = {}
        profiles = data.get('profiles')
        if not isinstance(profiles, dict) or not profiles:
            raise ConfigurationError('Catalog must define worker profiles')
        for role, info in profiles.items():
            identifier(role)
            try:
                default = ModelSelection(**info['default'])
                models = {ModelSelection(item['provider'], item['model']) for item in info['models'] if item.get('compatible', True)}
            except (KeyError, TypeError) as exc:
                raise ConfigurationError(f'Invalid model catalog for {role}') from exc
            if default not in models:
                raise ConfigurationError(f'Default model is unavailable for {role}')
            self._profiles[role] = frozenset(models)
            self._defaults[role] = default

    @classmethod
    def from_file(cls, path: Path):
        path = Path(path)
        catalog = cls(json.loads(path.read_text()))
        catalog._source = (path, path.stat().st_mtime_ns)
        return catalog

    def _refresh(self):
        """Pick up a re-exported catalog without a restart; an unreadable or invalid file keeps the last good one."""
        if not self._source:
            return
        path, seen = self._source
        try:
            stamp = path.stat().st_mtime_ns
            if stamp == seen:
                return
            self._source = (path, stamp)
            fresh = type(self)(json.loads(path.read_text()))
        except (OSError, ValueError, ConfigurationError):
            return
        self._profiles, self._defaults = fresh._profiles, fresh._defaults

    def defaults(self) -> dict[str, ModelSelection]:
        self._refresh()
        return dict(self._defaults)

    def choices(self, profiles: tuple[str, ...]) -> list[ModelSelection]:
        self._refresh()
        if not profiles:
            raise ConfigurationError('No assigned worker profiles are recorded for this task')
        unknown = set(profiles) - self._profiles.keys()
        if unknown:
            raise ConfigurationError('Configure model catalog for: ' + ', '.join(sorted(unknown)))
        choices = set.intersection(*(set(self._profiles[p]) for p in profiles))
        return sorted(choices, key=lambda choice: (choice.provider, choice.model))

    def validate(self, selection: ModelSelection, profiles: tuple[str, ...]) -> None:
        if selection not in self.choices(profiles):
            raise ConfigurationError('Model is not configured and compatible for every affected profile')
