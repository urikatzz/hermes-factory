"""Normalize worker evidence without consulting mutable profile defaults."""
from dataclasses import dataclass
import json
import re
from pathlib import PurePath


@dataclass(frozen=True)
class StageResult:
    valid: bool
    reason: str
    kind: str
    run_id: int | None
    metadata: dict


VERDICTS = {'prepare': ('DONE','BLOCKED'), 'implement': ('DONE','BLOCKED'), 'repair': ('DONE','BLOCKED'), 'review': ('NO_BLOCKING_FINDINGS','CHANGES_REQUIRED'), 'verify': ('PASS','FAIL')}


def normalize_handoff(task, run, expected_stage):
    kind = expected_stage['kind']
    def invalid(reason):
        return StageResult(False, reason, kind, run.get('id') if run else None, {})
    if not run or task.get('status') != 'done' or expected_stage.get('active_run_id', task.get('current_run_id')) != run.get('id'):
        return invalid('Missing or stale completed worker run')
    if run.get('task_id') != task.get('id') or run.get('profile') != expected_stage['profile'] or not run.get('claim_lock') or run.get('outcome') != 'completed':
        return invalid('Worker ownership evidence is missing')
    metadata = run.get('metadata') or {}
    if isinstance(metadata,str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            return invalid('Malformed handoff metadata')
    if not isinstance(metadata,dict):
        return invalid('Malformed handoff metadata')
    metadata = dict(metadata)
    metadata['source_profile'] = expected_stage['profile']
    required = dict(contract='factory-worker/v2',workflow_contract='factory-workflow/v1',root=expected_stage['root_id'],stage_key=expected_stage['stage_key'],cycle=expected_stage['cycle']+1)
    if any(metadata.get(k) != v for k,v in required.items()):
        return invalid('Workflow handoff identity or contract mismatch')
    verdict = metadata.get('verdict')
    if verdict not in VERDICTS[kind]:
        return invalid('Unsupported stage verdict')
    summary = run.get('summary') or ''
    header = f"VERDICT={verdict} STAGE={metadata.get('stage')} CYCLE={metadata['cycle']} MANIFEST={metadata.get('manifest_sha12')}"
    first = summary.split('\n',1)[0]
    # The header must lead the summary exactly; a worker may append a short note after it on the same line.
    if first != header and not (first.startswith(header) and not first[len(header)].isalnum()):
        return invalid('Summary contradicts handoff metadata')
    if verdict == 'BLOCKED':
        return StageResult(True, '', kind, run['id'], metadata)
    if kind != 'prepare' and not re.fullmatch('[a-f0-9]{12}', str(metadata.get('manifest_sha12',''))):
        return invalid('Missing code manifest digest')
    if kind in ('prepare','implement','repair'):
        ids = metadata.get('ac_ids')
        if not isinstance(ids,list) or not ids or any(not isinstance(v,str) or not re.fullmatch(r'AC(?:[0-9]+|-GATE)',v) for v in ids) or len(set(ids)) != len(ids):
            return invalid('Missing acceptance criteria')
    if kind in ('prepare','review','verify'):
        artifacts = metadata.get('artifacts')
        if not isinstance(artifacts,list) or not artifacts or any(not isinstance(p,str) or not p.startswith('/') for p in artifacts):
            return invalid('Missing retained report artifacts')
        retained = expected_stage.get('retained_artifacts')
        if retained is not None and any(path not in retained for path in artifacts):
            return invalid('Artifact is not a retained completion attachment')
    findings = metadata.get('findings',[])
    if not isinstance(findings,list) or len(findings)>15:
        return invalid('Invalid findings list')
    for finding in findings:
        parts = finding.split('|',4) if isinstance(finding,str) else []
        if len(parts)!=5 or parts[1] not in ('BLOCKER','HIGH','MEDIUM','LOW','NIT'):
            return invalid('Invalid finding schema')
    truncated = metadata.get('findings_truncated',0)
    if type(truncated) is not int or truncated<0:
        return invalid('Invalid truncated finding count')
    checks = metadata.get('failed_checks',[])
    if not isinstance(checks,list):
        return invalid('Invalid failed check evidence')
    normalized_checks=[]
    for check in checks:
        if isinstance(check,str) and check.strip():
            normalized_checks.append(dict(cmd=check,preexisting=check.strip().lower().startswith('preexisting:')))
        elif isinstance(check,dict) and isinstance(check.get('cmd',check.get('command')),str) and type(check.get('preexisting',False)) is bool:
            normalized_checks.append({**check,'cmd':check.get('cmd',check.get('command')),'preexisting':check.get('preexisting',False)})
        else:
            return invalid('Invalid failed check evidence')
    metadata['failed_checks'] = normalized_checks
    failed_count=metadata.get('checks_failed',len(normalized_checks))
    if type(failed_count) is not int or failed_count<0:
        return invalid('Invalid failed check count')
    metadata['checks_failed']=failed_count
    if kind == 'verify':
        archive_pattern = r'src-' + re.escape(metadata['manifest_sha12']) + r'(?:_[0-9]+)?\.tgz'
        archives = [path for path in metadata['artifacts'] if re.fullmatch(archive_pattern,PurePath(path).name)]
        attached = metadata.get('snapshot_attached',True)
        if type(attached) is not bool or (attached and len(archives)!=1) or (not attached and archives):
            return invalid('Missing or ambiguous retained manifest snapshot')
        metadata['snapshot'] = archives[0] if attached else None
        metadata['snapshot_attached'] = attached
        commands = metadata.get('publish_commands')
        if not isinstance(commands,list) or not commands or any(not isinstance(command,str) or not command.strip() for command in commands):
            return invalid('Missing manual publishing commands')
        gaps = metadata.get('environment_gaps',{})
        if not isinstance(gaps,dict) or any(not isinstance(key,str) or not isinstance(value,str) for key,value in gaps.items()):
            return invalid('Invalid environment evidence')
        results = metadata.get('ac_results')
        allowed = ('pass','fail','unverified:code','unverified:harness','unverified:environment')
        if not isinstance(results,dict) or not results or any(v not in allowed for v in results.values()):
            return invalid('Missing or unsupported acceptance results')
        if metadata.get('release_audit') not in ('PASS','FAIL'):
            return invalid('Missing release audit result')
    return StageResult(True, '', kind, run['id'], metadata)
