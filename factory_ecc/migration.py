"""Save guidance using the existing optimistic, immutable template service."""
from dataclasses import asdict
from difflib import unified_diff
from pathlib import Path
import json

from .files import canonical, write_json
from .guidance import guidance_digest, transform_workflow


def build_preview(templates):
    # Import only in the adapter: offline benchmark users do not need Hermes.
    from factory_dashboard.workflow_types import WorkflowDefinition
    changes = []
    for document in templates.list():
        before = {k: v for k, v in document.items() if k != 'archived'}
        after = transform_workflow(before)
        WorkflowDefinition.from_document(after)
        if before == after:
            continue
        diffs = {}
        for kind in ('prepare', 'implement', 'repair'):
            diffs[kind] = ''.join(unified_diff(
                before[kind]['instructions'].splitlines(keepends=True),
                after[kind]['instructions'].splitlines(keepends=True),
                fromfile=kind + '/before', tofile=kind + '/after'))
        changes.append(dict(template_id=before['template_id'], revision=before['revision'],
                            before=before, after=after, instruction_diffs=diffs))
    return json.loads(canonical(dict(schema='factory-ecc-migration/v1', settings_db=str(templates._store.path.resolve()),
                guidance_digest=guidance_digest(), defaults=templates.defaults(), changes=changes)))


def apply_preview(templates, preview, receipt_dir):
    if preview != build_preview(templates):
        raise ValueError('Preview is stale, edited, or belongs to a different settings database; regenerate it')
    receipt_dir = Path(receipt_dir)
    if receipt_dir.is_symlink():
        raise ValueError('Refusing symlinked receipt directory')
    receipt_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_json(receipt_dir / 'preview.json', preview, exclusive=True)
    result = dict(schema='factory-ecc-migration-result/v1', status='complete', applied=[], error=None)
    for change in preview['changes']:
        receipt_path = receipt_dir / (change['template_id'] + '.json')
        # This durable before image survives process termination between save and receipt update.
        receipt = dict(schema='factory-ecc-receipt/v1', settings_db=preview['settings_db'],
                       guidance_digest=preview['guidance_digest'], before=change['before'],
                       after={**change['after'], 'revision': change['revision'] + 1}, state='prepared')
        write_json(receipt_path, receipt, exclusive=True)
        try:
            saved = templates.save(change['after'], change['revision'])
        except Exception as exc:
            result.update(status='partial' if result['applied'] else 'failed', error=str(exc))
            break
        receipt.update(state='applied', after=asdict(saved))
        write_json(receipt_path, receipt)
        result['applied'].append(dict(template_id=saved.template_id, revision=saved.revision, receipt=str(receipt_path)))
        write_json(receipt_dir / 'result.json', result)
    write_json(receipt_dir / 'result.json', result)
    return result


def rollback_receipt(templates, receipt):
    if (receipt.get('schema') != 'factory-ecc-receipt/v1'
            or receipt.get('settings_db') != str(templates._store.path.resolve())):
        raise ValueError('Receipt belongs to a different settings database or schema')
    before, after = receipt['before'], receipt['after']
    if (before.get('template_id') != after.get('template_id')
            or type(before.get('revision')) is not int
            or after.get('revision') != before['revision'] + 1
            or receipt.get('guidance_digest') != guidance_digest()):
        raise ValueError('Receipt template/revision/guidance identity is inconsistent')
    historical = templates.get(before['template_id'], before['revision'])
    expected_after = {**transform_workflow(before), 'revision': before['revision'] + 1}
    if (canonical(asdict(historical)) != canonical(before)
            or canonical(expected_after) != canonical(after)):
        raise ValueError('Receipt differs from stored historical revision or guidance transform')
    current = templates.get(after['template_id'])
    if canonical(asdict(current)) != canonical(after):
        raise ValueError('Template changed after migration; review rather than overwrite')
    # Restoring creates a new revision; old snapshots and all history remain intact.
    return templates.save(before, current.revision)
