#!/usr/bin/env python3
"""Preview/install project workflows with private backups and immutable v1 snapshots."""
import argparse
from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'runtime/factory-dashboard'
sys.path.insert(0, str(SOURCE))

from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.project_policy import V2_PROFILES
from factory_dashboard.project_references import INSPECTING_PROFILES
from factory_dashboard.task_settings_store import TaskSettingsStore, encode
from factory_dashboard.workflow_types import WorkflowDefinition

BASE = '''# Project workflow v2

When your card includes PROJECT_WORKFLOW_VERSION 2, its captured stage instructions override legacy role sequencing.
The controller owns all stage creation, dependencies and gates. Never create, reassign or complete another stage.
Preparation is read-only against PROJECT_DIR; write retained plans/reports only in your assigned scratch workspace.
In a managed scope stage, factory-orchestrator inspects read-only and retains PLAN.md plus project_scope metadata.
For factory-retro retain RETRO.md instead of PLAN.md. For a small task, its TASK acceptance IDs override project-wide IDs;
read inherited director and architecture plans, preserve completed task outputs, and keep the cumulative manifest.
The architect receives director plans before producing PLAN.md and project-plan.json; it never implements.
If a project lacks a required art/audio bible, directors plan a style-bible creation task before asset work; they do not
require an already-existing game. Preserve any existing approved bible unless the captured task explicitly changes it.
Verifier must explicitly pass before reviewers are created. Any repaired implementation starts with verification again.
For perceptual review, obey the card's retained comparison.json contract. Final art review requires actual in-engine
rendering. Missing perception is unavailable evidence, not a NIT, a waiver or an approval.
Asset mismatch findings route to artist/sound-designer, code findings to fixer. Never redefine director intent to pass.
A plan reviewer retains PLAN-REVIEW.md and reports plan defects as findings; it writes no plan of its own.
If a failure comes from a wrong task plan or acceptance criterion, set metadata.plan_defect instead of forcing a repair.
The architect sets metadata.scope_additions when the captured scope omits art, audio, UI or UX the work needs.
factory-retro proposes improvements only; changing Factory behavior requires a separate approved implementation task.
All existing Git/publishing restrictions, approval floors and factory-worker handoff identity checks still apply.

'''
AUTHORITY_LINES_PREVIOUS = '''Authority, highest first: human-approved decisions and references > GDD > style bible and architecture > implementation plan >
implementation and tests. A lower layer refines a higher one; it never contradicts, replaces or silently drops it. When the card lists
approved_references, open each image yourself with vision_analyze before you plan, decide or judge anything visual (a path or hash is not an
inspection), cite its V requirement ids, and retain reference-inspection.json as the card says. A rule or criterion that forbids, defers or excludes
something an approved reference shows is a defect in the lower layer. Grey-box simplifies gameplay and production assets; it never waives an approved
composition, palette, HUD or defining visual characteristic. Only a human-approved deferral listed in approved_references postpones a requirement.
Factory mockups and screenshots are derived evidence, never the source of truth.
'''
AUTHORITY_LINES = '''Authority, highest first: human-approved decisions and references > GDD > style bible and architecture > implementation plan >
implementation and tests. A lower layer refines a higher one; it never contradicts, replaces or silently drops it. When the card lists
approved_references, follow this order and cite its V requirement ids. Only when your card has a "Mandatory reference inspection" section, open each image
yourself with vision_analyze before you plan, decide or judge anything visual (a path or hash is not an inspection) and retain reference-inspection.json
as that section says; a role whose card has no such section never needs to view images and never blocks for lacking vision. A rule or criterion that forbids, defers or excludes
something an approved reference shows is a defect in the lower layer. Grey-box simplifies gameplay and production assets; it never waives an approved
composition, palette, HUD or defining visual characteristic. Only a human-approved deferral listed in approved_references postpones a requirement.
Factory mockups and screenshots are derived evidence, never the source of truth.
'''
TOOL_LINES = '''In a managed stage the file and terminal toolsets of your profile are enabled for your scratch workspace, whatever your role text says about chat mode.
Sentences such as "your tools are kanban and skills only" or "you never write files" describe chat mode and do not apply: write the retained report with write_file
under $HERMES_KANBAN_WORKSPACE and attach it with kanban_complete(artifacts=[that absolute path]); a completion without the attachment is rejected.
'''
ENDING = 'All existing Git/publishing restrictions, approval floors and factory-worker handoff identity checks still apply.\n'
_WITHOUT_TOOLS = BASE.replace(ENDING, AUTHORITY_LINES + ENDING)
MANAGED = BASE.replace(ENDING, TOOL_LINES + AUTHORITY_LINES + ENDING)
_PREVIOUS_AUTHORITY = BASE.replace(ENDING, AUTHORITY_LINES_PREVIOUS + ENDING)
PLANNING_LINES = '''A plan reviewer retains PLAN-REVIEW.md and reports plan defects as findings; it writes no plan of its own.
If a failure comes from a wrong task plan or acceptance criterion, set metadata.plan_defect instead of forcing a repair.
The architect sets metadata.scope_additions when the captured scope omits art, audio, UI or UX the work needs.
'''
BIBLE_LINES = '''If a project lacks a required art/audio bible, directors plan a style-bible creation task before asset work; they do not
require an already-existing game. Preserve any existing approved bible unless the captured task explicitly changes it.
'''
# Blocks written by earlier releases; anything else was edited by hand and is left for manual review.
PERCEPTION_LINE = 'rendering. Missing perception is unavailable evidence, not a NIT, a waiver or an approval.\n'
LISTENING_LINES = '''rendering. Audio review requires a capable listening tool or retained human listening evaluation. Never claim to hear
audio from waveforms or loudness. Missing perception is unavailable evidence, not a NIT, a waiver or an approval.
'''
_WITH_AUDIO_REVIEW = BASE.replace(PERCEPTION_LINE, LISTENING_LINES)
RELEASED = (_WITHOUT_TOOLS, _PREVIOUS_AUTHORITY, BASE, _WITH_AUDIO_REVIEW, _WITH_AUDIO_REVIEW.replace(PLANNING_LINES, ''),
            _WITH_AUDIO_REVIEW.replace(PLANNING_LINES, '').replace(BIBLE_LINES, ''))
assert len({MANAGED, *RELEASED}) == 7


# The inspecting roles, plus both possible plan reviewers and the other visual reviewers.
VISION_PROFILES = (*INSPECTING_PROFILES, 'claude-reviewer', 'codex-reviewer', 'ui-reviewer', 'ux-reviewer', 'verifier')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def managed_text(original, *, skill=False):
    marker = '# Project workflow v2\n'
    start = original.find(marker)
    if start >= 0:
        ending = 'All existing Git/publishing restrictions, approval floors and factory-worker handoff identity checks still apply.\n\n'
        end = original.find(ending, start)
        if end < 0:
            raise ConfigurationError('Edited project managed block requires manual review')
        end += len(ending)
        if original[start:end] not in (MANAGED, *RELEASED):
            raise ConfigurationError('Edited project managed block requires manual review')
        return original[:start] + MANAGED + original[end:]
    if skill:
        end = original.find('\n---', 4) + 4 if original.startswith('---\n') else 0
        return original[:end] + '\n\n' + MANAGED + original[end:]
    return MANAGED + original


def activate_templates(store):
    """Single sidecar transaction: new heads only, never modify captured snapshots."""
    with store._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        roles = store._defaults(conn).roles
        if set(V2_PROFILES) - roles.keys():
            raise ConfigurationError('Configure all project workflow profiles before activation')
        changed = []
        for row in conn.execute('SELECT t.id,t.revision,r.document FROM factory_workflow_templates t JOIN factory_workflow_revisions r ON r.template_id=t.id AND r.revision=t.revision WHERE t.archived=0').fetchall():
            document = json.loads(row['document'])
            if document.get('execution_version', 1) == 2:
                continue
            document.update(execution_version=2, revision=row['revision'] + 1)
            WorkflowDefinition.from_document(document)
            conn.execute('INSERT INTO factory_workflow_revisions VALUES(?,?,?)', (row['id'], document['revision'], encode(document)))
            conn.execute('UPDATE factory_workflow_templates SET revision=? WHERE id=? AND revision=?', (document['revision'], row['id'], row['revision']))
            changed.append(dict(template_id=row['id'], before=row['revision'], after=document['revision']))
        return changed


def settings_fingerprint(path):
    with sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) as conn:
        data = dict(defaults=conn.execute('SELECT revision,roles FROM factory_defaults').fetchall(),
                    templates=conn.execute('SELECT id,revision,archived FROM factory_workflow_templates ORDER BY id').fetchall(),
                    mapping=conn.execute('SELECT revision,templates FROM factory_workflow_defaults').fetchall())
    return digest(json.dumps(data, sort_keys=True).encode())


def release_files(home):
    import yaml
    from factory_dashboard.task_settings import RoleSettings
    home = home.resolve()
    baseline = json.loads((REPO / 'runtime/baseline-sha256.json').read_text())
    files = {}
    for path in SOURCE.rglob('*'):
        if not path.is_file() or '__pycache__' in path.parts:
            continue
        relative = path.relative_to(SOURCE)
        target = home / 'factory-dashboard' / relative
        if target.exists() and relative.as_posix() in baseline:
            actual = digest(target.read_bytes())
            known = baseline[relative.as_posix()]
            # A list records every released digest of a file that changed in more than one release.
            if actual not in (*([known] if isinstance(known, str) else known), digest(path.read_bytes())):
                raise ConfigurationError('Installed source changed since baseline: ' + str(relative))
        files[target] = path.read_bytes()
    source_store = TaskSettingsStore(home / 'state/factory/task-settings.db', create=False)
    defaults = source_store.read_defaults()
    if 'architect' not in defaults.roles:
        raise ConfigurationError('Architect model settings are required')
    choice = defaults.roles.get('factory-retro', defaults.roles['architect'])
    roles = {**defaults.roles, 'factory-retro': choice}
    catalog_path = home / 'state/factory/model-catalog.json'
    catalog = json.loads(catalog_path.read_text())
    if 'factory-retro' not in catalog['profiles']:
        catalog['profiles']['factory-retro'] = json.loads(json.dumps(catalog['profiles']['architect']))
    files[catalog_path] = (json.dumps(catalog, indent=2, sort_keys=True) + '\n').encode()
    skill_source = REPO / 'runtime/factory-skills/worker/factory-retro'
    for path in skill_source.iterdir():
        files[home / 'factory-skills/worker/factory-retro' / path.name] = path.read_bytes()
    files[home / 'profiles/factory-retro/SOUL.md'] = (skill_source / 'SOUL.md').read_bytes()
    # Copy only profile configuration/credentials, never sessions or caches.
    architect = home / 'profiles/architect'
    retro = home / 'profiles/factory-retro'
    retro_config = retro / 'config.yaml'
    config = yaml.safe_load((retro_config if retro_config.exists() else architect / 'config.yaml').read_text())
    config['model'] = dict(provider=choice.provider, default=choice.model)
    config.setdefault('agent', {})['reasoning_effort'] = choice.effort
    config.setdefault('kanban', {})['dispatch_in_gateway'] = False
    config.setdefault('platform_toolsets', {})['cli'] = ['kanban', 'file', 'terminal']
    files[retro_config] = yaml.safe_dump(config, sort_keys=False).encode()
    for name in ('.env', 'auth.json'):
        if not (retro / name).exists() and (architect / name).is_file():
            files[retro / name] = (architect / name).read_bytes()
    owners = [home, *sorted(p for p in (home / 'profiles').iterdir() if (p / 'plugins/factory-models').is_dir()), retro]
    owners = list(dict.fromkeys(owners))
    # Profile-local plugin copies must enforce the same execution contract.
    module_path = SOURCE / 'scripts/bundle_factory_plugin.py'
    spec = importlib.util.spec_from_file_location('release_bundle', module_path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        bundle = module.bundle_plugin(Path(directory) / 'factory-models')
        for owner in owners:
            for path in bundle.rglob('*'):
                if path.is_file():
                    files[owner / 'plugins/factory-models' / path.relative_to(bundle)] = path.read_bytes()
    for owner in owners:
        path = owner / 'config.yaml'
        raw = files.get(path, path.read_bytes() if path.exists() else None)
        if raw is None:
            raise ConfigurationError('Missing profile configuration: ' + str(owner))
        configuration = yaml.safe_load(raw)
        roster = configuration.setdefault('kanban', {}).setdefault('dispatch_profiles', [])
        for role in V2_PROFILES:
            if role not in roster:
                roster.append(role)
        if owner.name in VISION_PROFILES:
            # These roles decide or judge visuals against approved reference images: they must be able to open images.
            tools = configuration.setdefault('platform_toolsets', {}).setdefault('cli', [])
            if 'vision' not in tools:
                tools.append('vision')
        if owner.name == 'factory-orchestrator':
            tools = configuration.setdefault('platform_toolsets', {}).setdefault('cli', [])
            for tool in ('file', 'terminal'):
                if tool not in tools:
                    tools.append(tool)
        files[path] = yaml.safe_dump(configuration, sort_keys=False).encode()
        soul = owner / 'SOUL.md'
        if owner != home and soul.is_file() and owner.name in V2_PROFILES and owner.name != 'factory-retro':
            original = soul.read_text()
            files[soul] = managed_text(original).encode()
    worker = home / 'factory-skills/worker/factory-worker/SKILL.md'
    original = worker.read_text()
    files[worker] = managed_text(original, skill=True).encode()
    return files, roles


def preview(home, files):
    home = home.resolve()
    changes = []
    for target, content in sorted(files.items()):
        if target.is_symlink() or not target.resolve().is_relative_to(home.resolve()):
            raise ConfigurationError('Refusing symlinked/outside release path: ' + str(target))
        before = digest(target.read_bytes()) if target.exists() else None
        after = digest(content)
        if before != after:
            changes.append(dict(path=str(target.relative_to(home)), before=before, after=after))
    return dict(schema='factory-project-install/v2', home=str(home),
                settings_fingerprint=settings_fingerprint(home / 'state/factory/task-settings.db'), changes=changes)


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def install(home, expected, backup):
    home = home.resolve()
    files, roles = release_files(home)
    actual = preview(home, files)
    if actual != expected:
        raise ConfigurationError('Preview is stale; generate a fresh preview')
    if backup.exists():
        raise ConfigurationError('Use a new private backup directory')
    backup.mkdir(parents=True, mode=0o700)
    database = home / 'state/factory/task-settings.db'
    with sqlite3.connect('file:' + str(database) + '?mode=ro', uri=True) as source, sqlite3.connect(backup / 'task-settings.db') as destination:
        source.backup(destination)
    os.chmod(backup / 'task-settings.db', 0o600)
    private_write(backup / 'prepared.json', json.dumps(actual, indent=2).encode())
    for change in actual['changes']:
        path = home / change['path']
        if path.exists():
            private_write(backup / 'files' / change['path'], path.read_bytes())
        private_write(path, files[path])
    store = TaskSettingsStore(database, create=False)
    with store._connect() as conn:
        conn.execute('BEGIN IMMEDIATE')
        if settings_fingerprint(database) != expected['settings_fingerprint']:
            raise ConfigurationError('Settings changed during install; templates were not activated')
        current = store._defaults(conn)
        if 'factory-retro' not in current.roles:
            conn.execute('UPDATE factory_defaults SET revision=revision+1,roles=? WHERE id=1',
                         (encode({k:asdict(v) for k,v in roles.items()}),))
    revisions = activate_templates(store)
    result = dict(schema='factory-project-install-result/v2', backup=str(backup), files_changed=len(actual['changes']), revisions=revisions)
    private_write(backup / 'applied.json', json.dumps(result, indent=2).encode())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home()/'.hermes')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--preview', type=Path)
    group.add_argument('--apply-preview', type=Path)
    parser.add_argument('--backup-dir', type=Path)
    args = parser.parse_args();home = args.home.resolve()
    try:
        if args.preview:
            files, _ = release_files(home)
            result = preview(home, files)
            private_write(args.preview, json.dumps(result, indent=2).encode())
            print(json.dumps(dict(preview=str(args.preview), files_changed=len(result['changes']))))
        else:
            if not args.backup_dir:
                parser.error('--backup-dir is required when applying')
            print(json.dumps(install(home, json.loads(args.apply_preview.read_text()), args.backup_dir.resolve())))
    except (ConfigurationError, OSError, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
