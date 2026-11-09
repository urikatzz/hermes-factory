"""Immutable model choices; historical attempts never consult mutable defaults."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


class ConfigurationError(ValueError):
    pass


def identifier(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or value.startswith('-') or any(ord(c) < 32 for c in value):
        raise ConfigurationError('A nonempty identifier without control characters is required')
    return value


@dataclass(frozen=True)
class ModelSelection:
    provider: str
    model: str

    def __post_init__(self):
        identifier(self.provider)
        identifier(self.model)


@dataclass(frozen=True)
class ResolvedSelection:
    selection: ModelSelection
    source: str
    revision: int


@dataclass(frozen=True)
class PolicySnapshot:
    revision: int
    defaults: Mapping[str, ModelSelection]
    overrides: Mapping[tuple[str, str], ModelSelection]

    def __post_init__(self):
        object.__setattr__(self, 'defaults', MappingProxyType(dict(self.defaults)))
        object.__setattr__(self, 'overrides', MappingProxyType(dict(self.overrides)))


class ModelPolicy:
    @staticmethod
    def resolve(snapshot: PolicySnapshot, board_key: str, root_id: str, role: str) -> ResolvedSelection:
        if (board_key, root_id) in snapshot.overrides:
            return ResolvedSelection(snapshot.overrides[board_key, root_id], 'task_override', snapshot.revision)
        if role not in snapshot.defaults:
            raise ConfigurationError(f'Configure a model default for {role}')
        return ResolvedSelection(snapshot.defaults[role], 'agent_default', snapshot.revision)
