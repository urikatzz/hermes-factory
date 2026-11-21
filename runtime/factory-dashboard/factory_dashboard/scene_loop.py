"""Attempt ledger for the full-scene repair loop: diagnose, repair what is responsible, re-render, re-score, never loop blindly.

State is a plain dict kept in the project document (`project['scene']`): {'attempts': [...], 'best': {...} | None}. Every rule here protects against a specific failure:
a repair without a diagnosis of the previous failure, a repeated repair with no new reason, regenerating assets nobody blamed, a regression that discards the best result,
and an exhausted budget that is silently extended. Nothing here changes the repair budget: that stays with the controller.
"""
import hashlib
import json

THRESHOLD = 80
MIN_DIAGNOSIS = 20


def signature(assets, instructions):
    """A stable identity for a repair: the assets it touches and what it asks of them (case and spacing insensitive)."""
    text = ' '.join(str(instructions or '').lower().split())
    return hashlib.sha256(json.dumps([sorted(set(assets or [])), text]).encode()).hexdigest()[:16]


def _attempts(state):
    return (state or {}).get('attempts', [])


def responsible_assets(differences):
    """Asset file names the scorer blamed, in rank order ('scene settings' is not an asset)."""
    out = []
    for item in differences or []:
        name = str(item.get('responsible', '')).strip()
        if name and name.lower() != 'scene settings' and name not in out:
            out.append(name)
    return out


def record_attempt(state, *, task_id, score, status, screenshot_sha256, differences, diagnosis, assets_sha256=None, repair=None, snapshot=None):
    """Append one scored attempt (idempotent per task id) and keep the best verified result. Returns the new state."""
    state = {'attempts': list(_attempts(state)), 'best': (state or {}).get('best')}
    if any(a['task_id'] == task_id for a in state['attempts']):
        return state
    if status not in ('pass', 'fail') or type(score) is not int:
        raise ValueError('only a real score is recorded: a blocked evaluation is not an attempt')
    attempt = dict(n=len(state['attempts']) + 1, task_id=task_id, score=score, status=status, screenshot_sha256=screenshot_sha256, differences=list(differences or []),
                   diagnosis=str(diagnosis or ''), assets_sha256=dict(assets_sha256 or {}), repair=repair or None, snapshot=snapshot)
    previous = state['attempts'][-1] if state['attempts'] else None
    attempt['delta'] = None if previous is None else score - previous['score']
    state['attempts'].append(attempt)
    best = state['best']
    if best is None or score > best['score']:    # a tie keeps the earlier verified result
        state['best'] = dict(n=attempt['n'], task_id=task_id, score=score, screenshot_sha256=screenshot_sha256, assets_sha256=dict(assets_sha256 or {}), snapshot=snapshot)
    return state


def best_result(state):
    return (state or {}).get('best')


def passed(state):
    last = _attempts(state)[-1] if _attempts(state) else None
    return bool(last) and last['status'] == 'pass' and last['score'] >= THRESHOLD


def check_repair_plan(state, plan):
    """Problems with a proposed repair (empty = allowed). plan: assets, instructions, diagnosis_of_previous, new_reason, reconsidered, restore_best."""
    attempts = _attempts(state)
    if not attempts:
        return [] if plan.get('assets') else ['a repair must name the assets it changes']
    last, problems = attempts[-1], []
    if last['status'] == 'pass':
        return ['the last attempt already passed; nothing to repair']
    assets = list(plan.get('assets') or [])
    if not assets:
        problems.append('a repair must name the assets it changes')
    if len(str(plan.get('diagnosis_of_previous') or '').strip()) < MIN_DIAGNOSIS:
        problems.append('the repair must include a diagnosis of why the previous attempt scored below %d' % THRESHOLD)
    blamed = set(responsible_assets(last['differences']))
    unblamed = [a for a in assets if a not in blamed]
    if unblamed and not str(plan.get('new_reason') or '').strip():
        problems.append('assets the scorer did not blame must not be regenerated without a stated reason: ' + ', '.join(unblamed))
    sig = signature(assets, plan.get('instructions'))
    if any(a.get('repair') and a['repair'].get('signature') == sig for a in attempts) and not str(plan.get('new_reason') or '').strip():
        problems.append('this repair repeats an earlier unsuccessful one; give a new reason or change the approach')
    if last['delta'] is not None and last['delta'] <= 0 and not plan.get('reconsidered'):
        problems.append('the score did not improve (%+d); reconsider the diagnosis or the repair strategy and say so' % last['delta'])
    best = best_result(state)
    if best and last['score'] < best['score'] and not plan.get('restore_best'):
        problems.append('the last attempt regressed from the best verified result (%d at attempt %d); restore the best assets first' % (best['score'], best['n']))
    return problems


def brief(state):
    """What the next repair card and the next reviewer must know: history, best result, remaining differences, forbidden repeats. '' when there is no history."""
    attempts = _attempts(state)
    if not attempts:
        return ''
    lines = ['SCENE SCORE HISTORY (full scene against the approved reference, pass is >= %d):' % THRESHOLD]
    for a in attempts:
        change = '' if a['delta'] is None else ' (%+d)' % a['delta']
        lines.append('- attempt %d: %d%s %s. Diagnosis: %s' % (a['n'], a['score'], change, a['status'].upper(), a['diagnosis'][:300]))
    best, last = best_result(state), attempts[-1]
    lines.append('Best verified result: attempt %d at %d%s. Preserve it: if the next attempt scores lower, restore its files.' % (best['n'], best['score'], (' (snapshot ' + best['snapshot'] + ')') if best.get('snapshot') else ''))
    if last['status'] == 'fail':
        lines.append('Remaining differences, largest effect first (repair the cause, not the score; keep every asset that is not named):')
        for d in last['differences']:
            lines.append('  * [impact %d] %s: %s -> responsible %s. Repair: %s' % (d['impact'], d['aspect'], d['description'], d['responsible'], d['repair']))
        lines.append('Your repair must start with a diagnosis of the previous failure, change only the responsible assets, and must not repeat an earlier repair without a new reason.')
        if last['delta'] is not None and last['delta'] <= 0:
            lines.append('The last repair did not raise the score (%+d): reconsider the diagnosis or change strategy.' % last['delta'])
    return '\n'.join(lines)


def exhaustion_report(state):
    """The remaining differences to hand a human when the repair budget is spent (never a reason to extend the budget)."""
    attempts = _attempts(state)
    if not attempts:
        return 'Repair budget exhausted before any full-scene score was obtained.'
    best, last = best_result(state), attempts[-1]
    top = '; '.join('%s (%s, impact %d)' % (d['description'], d['responsible'], d['impact']) for d in last['differences'][:4]) or 'none recorded'
    return ('Repair budget exhausted. Full-scene score history: %s. Best verified: attempt %d at %d (needs %d). Remaining differences in the last attempt: %s.'
            % (', '.join(str(a['score']) for a in attempts), best['n'], best['score'], THRESHOLD, top))
