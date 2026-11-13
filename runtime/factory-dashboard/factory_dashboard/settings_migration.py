"""Capture unfinished Factory work without rewriting board or session history."""
from dataclasses import asdict
import hashlib
import json
import re
from .model_policy import ConfigurationError
from .policy_store import RevisionConflict
from .task_identity import is_root, root_id
from .task_settings import RoleSettings

FINISHED = {'done', 'archived', 'cancelled'}


class SettingsMigration:
    def __init__(self, store, board_identity, read_board, read_profiles, read_old_overrides):
        self._store = store
        self._board = board_identity
        self._read_board = read_board
        self._read_profiles = read_profiles
        self._read_old_overrides = read_old_overrides

    def _inventory(self):
        tasks = sorted(self._read_board(), key=lambda t: t['id'])
        profiles = {role: RoleSettings(**{k: value[k] for k in ('provider', 'model', 'effort')})
                    for role, value in self._read_profiles().items()}
        old = self._read_old_overrides()
        lookup = {t['id']: t for t in tasks}
        groups = {}
        blockers = []
        for task in tasks:
            rid = root_id(task, lookup.get)
            if rid:
                groups.setdefault(rid, []).append(task)
            elif (task.get('title') or '').startswith('TICKET:'):
                groups.setdefault(task['id'], []).append(task)
            elif task.get('status') not in FINISHED and (re.search(r'\(t_[0-9a-f]+\)\s*$', task.get('title') or '') or re.match(r'^\[t_[0-9a-f]+\]', task.get('title') or '')):
                references = re.findall(r't_[0-9a-f]+', task.get('title') or '')
                if any(ref not in lookup for ref in references):
                    blockers.append('Unresolved parent for ' + task['id'])
        groups = {rid: members for rid, members in groups.items() if any(t.get('status') not in FINISHED for t in members)}
        legacy = {}
        for rid, members in groups.items():
            if rid in old:
                blockers.append('Resolve staged policy override before migration: ' + rid)
            if self._store.snapshot_for_task(self._board, rid):
                continue
            captured = {}
            for task in members:
                role = task.get('assignee')
                if not role and (task.get('title') or '').startswith('TICKET:'):
                    continue
                if role not in profiles:
                    blockers.append('Profile unavailable for ' + task['id'] + ': ' + str(role))
                    continue
                base = profiles[role]
                if any(task.get(k) for k in ('model_override', 'provider_override', 'reasoning_effort')):
                    captured[task['id']] = RoleSettings(task.get('provider_override') or base.provider,
                                                       task.get('model_override') or base.model,
                                                       task.get('reasoning_effort') or base.effort)
            legacy[rid] = captured
        document = {'tasks': tasks, 'profiles': {k: asdict(v) for k, v in profiles.items()}, 'old_overrides': old}
        digest = hashlib.sha256(json.dumps(document, sort_keys=True, default=str).encode()).hexdigest()
        report = {'digest': digest, 'roots': sorted(groups), 'blockers': blockers,
                  'running': [t['id'] for t in tasks if t.get('status') == 'running'],
                  'legacy_overrides': {rid: {tid: asdict(v) for tid, v in cards.items()} for rid, cards in legacy.items()}}
        return report, groups, profiles, legacy

    def inspect(self):
        return self._inventory()[0]

    def apply(self, expected_inventory_digest):
        report, groups, profiles, legacy = self._inventory()
        if report['digest'] != expected_inventory_digest:
            raise RevisionConflict('Migration inventory changed; inspect again')
        if report['blockers']:
            raise ConfigurationError('; '.join(report['blockers']))
        self._store.seed_defaults(profiles)
        for rid, members in groups.items():
            sid = self._store.capture_task(self._board, rid, 'legacy_migration', legacy.get(rid))
            for task in members:
                if task['id'] != rid:
                    self._store.bind_task(self._board, task['id'], sid, 'stage')
        return report
