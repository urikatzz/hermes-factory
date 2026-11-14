"""Immutable workflow definitions; profile capabilities are independent of models."""
from dataclasses import dataclass
from .model_policy import ConfigurationError

CAPABILITIES = {
    'architect': ('prepare',), 'developer': ('prepare', 'implement'),
    'fixer': ('prepare', 'implement', 'repair'),
    'claude-reviewer': ('review',), 'codex-reviewer': ('review',),
    'security-reviewer': ('review',), 'ux-reviewer': ('review',),
    'ui-reviewer': ('review',), 'verifier': ('verify',),
    'art-director': ('prepare',), 'artist': ('implement', 'repair'), 'art-reviewer': ('review',),
    'audio-director': ('prepare',), 'sound-designer': ('implement', 'repair'),
}
TASK_TYPES = ('feature', 'bug', 'chore', 'art', 'audio')


@dataclass(frozen=True)
class StageSpec:
    key: str
    kind: str
    profile: str
    instructions: str


@dataclass(frozen=True)
class WorkflowDefinition:
    template_id: str
    revision: int
    name: str
    description: str
    task_type: str
    prepare: StageSpec
    implement: StageSpec
    reviewers: tuple[StageSpec, ...]
    verify: StageSpec
    repair: StageSpec
    max_repairs: int

    @classmethod
    def from_document(cls, document):
        try:
            data = dict(document)
            for field in ('prepare', 'implement', 'verify', 'repair'):
                data[field] = StageSpec(**data[field])
            data['reviewers'] = tuple(StageSpec(**s) for s in data['reviewers'])
            definition = cls(**data)
        except (TypeError, KeyError, ValueError) as exc:
            raise ConfigurationError('Invalid workflow fields') from exc
        definition.validate()
        return definition

    def validate(self):
        for field, maximum, required in (('name', 100, True), ('description', 1000, False)):
            value = getattr(self, field)
            if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
                raise ConfigurationError(f'{field}: invalid length')
        if self.task_type not in TASK_TYPES:
            raise ConfigurationError('task_type: unsupported type')
        if type(self.max_repairs) is not int or not 0 <= self.max_repairs <= 3:
            raise ConfigurationError('max_repairs: choose an integer from 0 to 3')
        if not self.reviewers or not any(s.profile in ('claude-reviewer', 'codex-reviewer') for s in self.reviewers):
            raise ConfigurationError('reviewers: at least one code reviewer is required')
        stages = [(s, 'review') for s in self.reviewers]
        stages += [(getattr(self, kind), kind) for kind in ('prepare', 'implement', 'verify', 'repair')]
        keys = set()
        total = 0
        for stage, kind in stages:
            if stage.kind != kind or kind not in CAPABILITIES.get(stage.profile, ()):
                raise ConfigurationError(f'{kind}: unsupported profile capability')
            if not isinstance(stage.key, str) or not stage.key.isascii() or not stage.key.replace('-', '').replace('_', '').isalnum() or len(stage.key) > 64 or stage.key in keys:
                raise ConfigurationError(f'{kind}: invalid or duplicate stage key')
            keys.add(stage.key)
            if not isinstance(stage.instructions, str) or len(stage.instructions) > 4000:
                raise ConfigurationError(f'{kind}: instructions exceed 4000 characters')
            total += len(stage.instructions)
        if total > 20000:
            raise ConfigurationError('instructions: combined maximum is 20000 characters')
        profiles = [s.profile for s in self.reviewers]
        if len(profiles) != len(set(profiles)):
            raise ConfigurationError('reviewers: duplicate profile')


@dataclass(frozen=True)
class WorkflowBinding:
    snapshot_id: str
    definition: WorkflowDefinition
