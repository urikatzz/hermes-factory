"""Separate tool incidents from verification blockers.

A worker may hit the safety guard or a missing tool while doing otherwise sound work. That is an *incident* to record,
not by itself a blocked task. The controller blocks only when a required tool stayed unavailable (or when an unresolved
incident threatens an acceptance criterion). Rejected commands are always kept in the evidence; nothing is hidden.

Structured evidence, one entry per refused or unavailable command, in metadata ``tool_incidents``::

    {"command": "rm -rf scratch", "reason": "safety_guard", "required": false, "resolved": true,
     "alternative": "fw.py clean", "affected_criteria": []}

Results without ``tool_incidents`` keep the legacy rule: any non-empty ``blocked_tools`` blocks.
When both are present each ``blocked_tools`` command must appear in ``tool_incidents``, so a real blocker cannot be
dropped from the structured view.
"""
import re

AC_ID = re.compile(r'AC(?:[0-9]+|-GATE)')


def _command(entry):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        value = entry.get('cmd', entry.get('command'))
        return value if isinstance(value, str) else None
    return None


def validate_tool_incidents(metadata, ac_ids=None):
    """Return a reason when incident evidence is malformed, else None. ``ac_ids`` limits affected_criteria when known."""
    if 'tool_incidents' not in metadata:
        return None
    legacy = metadata.get('blocked_tools', [])
    if not isinstance(legacy, list):
        return 'Invalid blocked tool evidence'
    incidents = metadata['tool_incidents']
    if not isinstance(incidents, list):
        return 'Invalid tool incident evidence'
    commands = set()
    for item in incidents:
        if not isinstance(item, dict):
            return 'Invalid tool incident evidence'
        command, reason, alternative = item.get('command'), item.get('reason'), item.get('alternative')
        if not isinstance(command, str) or not command.strip() or not isinstance(reason, str) or not reason.strip():
            return 'Invalid tool incident evidence: command and reason are required'
        if type(item.get('required')) is not bool or type(item.get('resolved')) is not bool:
            return 'Invalid tool incident evidence: required and resolved must be booleans'
        if not isinstance(alternative, str):
            return 'Invalid tool incident evidence: alternative must be text (empty when none)'
        if item['resolved'] and not alternative.strip():
            return 'Invalid tool incident evidence: a resolved incident must name the alternative that worked'
        affected = item.get('affected_criteria')
        if not isinstance(affected, list) or any(not isinstance(a, str) or not AC_ID.fullmatch(a) for a in affected):
            return 'Invalid tool incident evidence: affected_criteria must list acceptance IDs'
        if ac_ids is not None and any(a not in ac_ids for a in affected):
            return 'Invalid tool incident evidence: affected criterion is not part of this task'
        commands.add(command.strip())
    for entry in legacy:
        command = _command(entry)
        if command is None or command.strip() not in commands:
            return 'Blocked tool is not accounted for in tool_incidents'
    return None


def tool_blockers(metadata):
    """Descriptions of what still blocks the stage; empty means execution may continue."""
    if 'tool_incidents' not in metadata:
        legacy = metadata.get('blocked_tools') or []
        return [f'blocked tool: {_command(e) or e}' for e in (legacy if isinstance(legacy, list) else [legacy])]
    blockers = []
    for item in metadata['tool_incidents']:
        if item['resolved']:
            continue
        if item['required'] or item['affected_criteria']:
            scope = ', '.join(item['affected_criteria']) or 'a required step'
            blockers.append(f"unresolved tool incident: {item['command']} ({item['reason']}) affects {scope}")
    return blockers
