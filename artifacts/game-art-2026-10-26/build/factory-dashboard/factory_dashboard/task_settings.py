"""Immutable Factory settings values, distinct from recorded session evidence."""
from dataclasses import dataclass
from types import MappingProxyType
from .model_policy import ConfigurationError, identifier

EFFORTS = ('none','minimal','low','medium','high','xhigh','max','ultra')

@dataclass(frozen=True)
class RoleSettings:
    provider: str
    model: str
    effort: str

    def __post_init__(self):
        identifier(self.provider);identifier(self.model)
        if self.effort not in EFFORTS:raise ConfigurationError('Invalid effort')

@dataclass(frozen=True)
class DefaultsRevision:
    revision: int
    roles: dict

    def __post_init__(self):
        object.__setattr__(self,'roles',MappingProxyType(dict(self.roles)))

@dataclass(frozen=True)
class TaskSnapshot:
    id: str
    board: str
    defaults_revision: int
    created_at: str
    origin: str
    roles: dict
    legacy_card_settings: dict
    workflow: object = None

    def __post_init__(self):
        for key in ('roles','legacy_card_settings'):
            object.__setattr__(self,key,MappingProxyType(dict(getattr(self,key))))
