"""Pure policy for same-manifest review, bounded repairs and human escalation."""
from dataclasses import dataclass

from .project_decisions import waiver_for
from .tool_incidents import tool_blockers


@dataclass(frozen=True)
class GateDecision:
    decision: str
    reason: str
    blocking: tuple = ()
    waived: tuple = ()


def evaluate_cycle(writer, readers, previous_cycle, max_repairs, repairs_used, context):
    if not writer.valid:
        return GateDecision('human_review',writer.reason)
    if writer.metadata['verdict']=='BLOCKED':
        return GateDecision('blocked',str(writer.metadata.get('blocked_reason','Writer blocked')))
    if not readers:
        return GateDecision('wait','Waiting for selected reviewers and verifier')
    blocking, waived = [], []
    for reader in readers:
        if not reader.valid:
            return GateDecision('human_review',reader.reason)
        data = reader.metadata
        reader_start=len(blocking)
        if data['manifest_sha12'] != writer.metadata['manifest_sha12']:
            return GateDecision('human_review','Review manifest does not match the writer')
        blockers=tool_blockers(data)
        if blockers:
            return GateDecision('human_review','Required tools or security checks could not run: '+'; '.join(blockers))
        if reader.kind=='verify':
            results = data['ac_results']
            if set(results) != set(writer.metadata['ac_ids']):
                return GateDecision('human_review','Acceptance coverage differs from the writer')
            unity_waived=False
            for ac,outcome in results.items():
                if outcome=='unverified:environment':
                    if context.get('unity_ci') and data.get('environment_gaps',{}).get(ac)=='unity_editor':
                        waived.append(ac+': pending repo CI (Unity)');unity_waived=True
                    else:
                        return GateDecision('human_review','Acceptance needs unavailable environment: '+ac)
                elif outcome!='pass':
                    blocking.append(ac+': '+outcome)
            failed_checks=data.get('failed_checks',[])
            if failed_checks or data.get('checks_failed',0):
                blocking.append('Verifier checks failed')
            if any(check['preexisting'] or check.get('fix_available') is False for check in failed_checks):
                return GateDecision('human_review','A required failed check is preexisting or has no available fix',tuple(blocking),tuple(waived))
            unity_only=unity_waived and all(value in ('pass','unverified:environment') for value in results.values()) and not failed_checks and not data.get('checks_failed',0)
            if data['release_audit']=='FAIL' or (data['verdict']=='FAIL' and not unity_only):
                blocking.append('Verifier or release audit failed')
        for finding in data.get('findings',[]):
            finding=data['source_profile']+':'+finding
            _,severity,ac,_,_ = finding.split('|',4)
            if severity in ('BLOCKER','HIGH') or (severity=='MEDIUM' and ac!='-'):
                waiver=waiver_for(finding,context.get('waivers'))
                if waiver:
                    # A scoped human waiver: the finding keeps its original text and is never counted as passed.
                    waived.append(f"{finding}: waived by human decision {waiver['id']}: {waiver['reason']}")
                else:
                    blocking.append(finding)
            else:
                waived.append(finding+': non-blocking finding retained')
        if data.get('findings_truncated',0)>0:
            blocking.append('Review remaining findings in retained report')
        if data.get('verdict')=='CHANGES_REQUIRED' and not data.get('findings'):
            return GateDecision('human_review','Reviewer requested changes without findings')
        if (data.get('preexisting') or data.get('fix_available') is False) and len(blocking)>reader_start:
            return GateDecision('human_review','Blocking evidence is preexisting or has no available fix',tuple(blocking))
    if not any(reader.kind=='verify' for reader in readers):
        return GateDecision('human_review','Independent verifier evidence is missing')
    if not blocking:
        return GateDecision('pass','All selected checks passed',(),tuple(waived))
    previous = set((previous_cycle or {}).get('blocking',[]))
    rejected = writer.metadata.get('rejected_findings',[])
    for finding in blocking:
        if finding in previous and any(str(item).split('|',1)[0] in (finding.split('|',1)[0],finding.split('|',1)[0].split(':',1)[-1]) for item in rejected):
            return GateDecision('human_review','Rejected blocking finding recurred',tuple(blocking),tuple(waived))
    if repairs_used>=max_repairs:
        return GateDecision('human_review','Captured repair limit reached',tuple(blocking),tuple(waived))
    return GateDecision('repair','Repair required',tuple(blocking),tuple(waived))
