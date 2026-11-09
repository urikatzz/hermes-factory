"""Allowlisted profile defaults; configuration files remain the source of truth."""
from dataclasses import asdict
import hashlib
from pathlib import Path
from threading import RLock
from .model_policy import ConfigurationError, ModelSelection
from .policy_store import RevisionConflict


class ProfileSettings:
    def __init__(self, hermes_home, catalog, decode_config, write_config, efforts):
        self._home = Path(hermes_home).resolve()
        self._catalog = catalog
        self._decode = decode_config
        self._write = write_config
        self._efforts = tuple(efforts)
        self._lock = RLock()

    def _path(self, role):
        if role not in self._catalog.defaults() or not role.replace('-', '').replace('_', '').isalnum():
            raise ConfigurationError('Unknown Factory profile')
        path = self._home / 'profiles' / role / 'config.yaml'
        if path.resolve() != path:
            raise ConfigurationError('Symlinked profile configuration is not writable')
        return path

    def _load(self, role):
        raw = self._path(role).read_bytes()
        config = self._decode(raw.decode())
        model = config['model']
        selection = ModelSelection(model['provider'], model['default'])
        public = {**asdict(selection), 'effort': config.get('agent', {}).get('reasoning_effort'),
                  'revision': hashlib.sha256(raw).hexdigest(), 'effort_choices': self._efforts}
        return config, public

    def read(self):
        with self._lock:
            return {role: self._load(role)[1] for role in self._catalog.defaults()}

    def save(self, role, selection, effort, revision):
        with self._lock:
            path = self._path(role)
            self._catalog.validate(selection, (role,))
            if effort not in self._efforts:
                raise ConfigurationError('Unsupported Hermes effort setting')
            config, current = self._load(role)
            if revision != current['revision']:
                raise RevisionConflict('Profile changed; reload and review before saving')
            config['model'].update(provider=selection.provider, default=selection.model)
            config.setdefault('agent', {})['reasoning_effort'] = effort
            self._write(path, config)
            # Do not report a failed save because a subsequent source read failed.
            return {**asdict(selection), 'effort': effort, 'saved': True}
