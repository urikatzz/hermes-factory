"""Pure benchmark summaries with explicit evidence and accounting coverage."""
from statistics import median

from .results import COUNTERS


def _rate(successes, denominator):
    return dict(successes=successes, denominator=denominator,rate=successes/denominator if denominator else None)


def _usage(trials, excluded=()):
    sessions = {s['id']:s for trial in trials for s in trial['sessions'] if s['id'] not in excluded}
    result = dict(recorded_sessions=len(sessions),trials_without_sessions=sum(not t['sessions'] for t in trials),
                  included_sessions=sum(s['included'] for s in sessions.values()),
                  excluded_shared_session_ids=sorted(set(excluded) & {s['id'] for t in trials for s in t['sessions']}))
    for field in ('actual_usd','estimate_usd') + COUNTERS:
        values=[s[field] for s in sessions.values() if s[field] is not None and not (field=='estimate_usd' and s['included'])]
        result[field]=sum(values) if values else None
        result[field+'_known_sessions']=len(values)
    return result


def summarize(taskset, trials):
    if trials.taskset_digest != taskset['digest']:
        raise ValueError('Report taskset differs from imported trials')
    memberships = {}
    for trial in trials:
        for session in trial['sessions']:
            memberships.setdefault(session['id'],set()).add(trial['variant_id'])
    shared = sorted(key for key,value in memberships.items() if len(value)>1)
    variants = []
    for variant in trials.variants:
        selected=[t for t in trials if t['variant_id']==variant['id']]
        counts={key:sum(t['classification']==key for t in selected)
                for key in ('success','failed','infrastructure_blocked','incomplete')}
        first=[t for t in selected if t['first_attempt'] is not None]
        row=dict(id=variant['id'],captured_settings=variant,imported=len(selected),counts=counts,
                 trials_with_incomplete_evidence=sum(not t['evidence_complete'] for t in selected),
                 first_attempt_success=_rate(sum(t['first_attempt'] is True for t in first),len(first)),
                 eventual_success=_rate(counts['success'],counts['success']+counts['failed']),
                 usage=_usage(selected,shared))
        row['cases']={case['id']:dict(imported=sum(t['case_id']==case['id'] for t in selected),
            counts={key:sum(t['case_id']==case['id'] and t['classification']==key for t in selected) for key in counts}) for case in taskset['cases']}
        for field in ('repairs','elapsed_seconds'):
            values=[t[field] for t in selected if t[field] is not None]
            row[field]=dict(known_trials=len(values),total=sum(values) if values else None,median=median(values) if values else None)
        variants.append(row)
    usage=_usage(trials);usage['shared_session_ids']=shared
    return dict(schema='factory-ecc-report/v1',taskset_digest=taskset['digest'],synthetic=trials.synthetic,
                imported_trials=len(trials),defined_cases=[c['id'] for c in taskset['cases']],variants=variants,usage=usage,
                limitations=['Operator-imported evidence is not independently authenticated.',
                    'Functional graders share a process with candidate code; review grading provenance.',
                    'No statistical superiority is established by this report.',
                    'Unknown costs and unlinked coordinator/infrastructure usage are not zero.'])


def _cell(value):
    return str(value).replace('|','\\|').replace('\n',' ').replace('\r',' ')


def _rate_text(value):
    return f"{value['successes']}/{value['denominator']}" + (f" ({value['rate']:.0%})" if value['rate'] is not None else ' (unknown)')


def render_markdown(report):
    label='SYNTHETIC — report mechanics only; no model evaluation' if report['synthetic'] else 'Operator-imported Factory benchmark'
    lines=['# '+label,'',f"Taskset: `{report['taskset_digest']}`. Imported trials: {report['imported_trials']}.",'',
           '| Variant | Imported | First attempt (known history) | Eventual (success + failed) | Blocked | Incomplete | Missing evidence |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for row in report['variants']:
        lines.append(f"| {_cell(row['id'])} | {row['imported']} | {_rate_text(row['first_attempt_success'])} | {_rate_text(row['eventual_success'])} | {row['counts']['infrastructure_blocked']} | {row['counts']['incomplete']} | {row['trials_with_incomplete_evidence']} |")
    lines += ['', 'Case coverage counts imported trials; unrun cases are shown as zero, not passing.', '',
              '| Variant | Case | Imported | Success | Failed | Blocked | Incomplete |','|---|---|---:|---:|---:|---:|---:|']
    for row in report['variants']:
        for case, coverage in row['cases'].items():
            counts=coverage['counts']
            lines.append(f"| {_cell(row['id'])} | {_cell(case)} | {coverage['imported']} | {counts['success']} | {counts['failed']} | {counts['infrastructure_blocked']} | {counts['incomplete']} |")
    lines += ['', '| Variant | Repairs total / known trials | Median seconds / known trials |','|---|---:|---:|']
    for row in report['variants']:
        repairs, elapsed=row['repairs'],row['elapsed_seconds']
        lines.append(f"| {_cell(row['id'])} | {repairs['total'] if repairs['total'] is not None else 'unknown'} / {repairs['known_trials']} | {elapsed['median'] if elapsed['median'] is not None else 'unknown'} / {elapsed['known_trials']} |")
    lines += ['', '| Scope | Actual USD (known sessions) | Estimates USD (known sessions) | Included sessions | Trials without sessions |','|---|---:|---:|---:|---:|']
    for name, usage in [('Overall',report['usage'])]+[(row['id'],row['usage']) for row in report['variants']]:
        def cost(field):
            return ('unknown' if usage[field] is None else f"{usage[field]:.4f}")+f" ({usage[field+'_known_sessions']})"
        lines.append(f"| {_cell(name)} | {cost('actual_usd')} | {cost('estimate_usd')} | {usage['included_sessions']} | {usage['trials_without_sessions']} |")
    lines += ['', 'Shared sessions are counted once overall and excluded from variant costs: '+(', '.join(_cell(s) for s in report['usage']['shared_session_ids']) or 'none'), '',
              'Token counters are separate in the JSON report; no combined token total is invented.', '', 'Limitations:', '']
    lines += ['- '+v for v in report['limitations']]
    return '\n'.join(lines)+'\n'
