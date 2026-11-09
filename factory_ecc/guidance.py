"""Original Factory guidance adapted from ECC research and retrieval concepts."""
from copy import deepcopy
import hashlib

BEGIN = '<!-- factory-ecc-guidance/v1:begin -->'
END = '<!-- factory-ecc-guidance/v1:end -->'
RETRIEVAL = '''Context retrieval: use the assigned workspace and permitted parent artifacts only.
Start with repository terms and likely entry points; inspect relevant callers and tests.
Name missing context, refine the search, and reassess after at most three refinement
rounds. Continue necessary reading; the bound never permits guessing requirements.
Check PLAN.md references against this workspace. Record unresolved gaps and supporting
paths/reasons in PLAN.md during preparation, or the existing report during later stages.
Respect read-only preparation, manifest snapshots, and the existing worker contract.
Keep detailed evidence in retained artifacts, not extra handoff metadata.'''
RESEARCH = '''Research before planning: search the assigned repository for existing behavior,
conventions, and extension points. For relevant dependencies/integrations, consult
available approved documentation or registries. Never add tools, expand network policy,
or treat unavailable search channels as proof that no solution exists.
In PLAN.md record the need, inspected paths, reusable solutions, selected approach and
reasons, alternatives when architecture matters, unavailable channels, and context gaps.
External research is conditional; local evidence is always the starting point.'''


def _block(kind):
    text = RESEARCH + '\n\n' + RETRIEVAL if kind == 'prepare' else RETRIEVAL
    return BEGIN + '\n' + text + '\n' + END


def guidance_digest():
    return hashlib.sha256('\n'.join(_block(k) for k in ('prepare', 'implement', 'repair')).encode()).hexdigest()


def transform_workflow(document):
    result = deepcopy(document)
    for kind in ('prepare', 'implement', 'repair'):
        instructions = result[kind]['instructions']
        block = _block(kind)
        if 'factory-ecc-guidance/' in instructions:
            if instructions.count(BEGIN) != 1 or instructions.count(END) != 1 or block not in instructions:
                raise ValueError(f'{kind}: edited, unknown or malformed guidance block')
            remainder = instructions.replace(block, '', 1)
            if 'factory-ecc-guidance/' in remainder:
                raise ValueError(f'{kind}: duplicate guidance block')
        else:
            result[kind]['instructions'] = instructions + ('\n\n' if instructions else '') + block
    return result
