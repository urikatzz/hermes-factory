"""Read-only view of the hermes_otel plugin's local live store (spans/metrics/logs)."""
from pathlib import Path
import json
import sqlite3
import time

DB_NAME = 'hermes_otel_live.db'
_TOKEN_KEYS = ('gen_ai.usage.total_tokens', 'llm.token_count.total')
_COST_KEYS = ('hermes.cost.usage',)
_MODEL_KEYS = ('gen_ai.request.model', 'llm.model_name', 'gen_ai.response.model')


def _family(name):
    name = name or ''
    for prefix in ('llm', 'api', 'tool', 'subagent', 'approval', 'session', 'agent'):
        if name == prefix or name.startswith(prefix + '.') or name.startswith(prefix + ' '):
            return prefix
    return 'other'


def _first(attrs, keys):
    for key in keys:
        if attrs.get(key) is not None:
            return attrs[key]
    return None


class OtelSource:
    def __init__(self, hermes_home):
        home = Path(hermes_home)
        self._paths = [home / DB_NAME, *sorted(home.glob(f'profiles/*/{DB_NAME}'))]

    def _rows(self, sql, args=()):
        rows = []
        for path in self._paths:
            if not path.is_file():
                continue
            try:
                with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=1) as conn:
                    conn.row_factory = sqlite3.Row
                    rows.extend(dict(r) for r in conn.execute(sql, args))
            except sqlite3.Error:
                continue
        return rows

    def summary(self, hours=24):
        since_ns = int((time.time() - hours * 3600) * 1e9)
        stores = [str(p) for p in self._paths if p.is_file()]
        counts = {}
        for row in self._rows('SELECT kind, COUNT(*) n, MAX(ts) last FROM events GROUP BY kind'):
            entry = counts.setdefault(row['kind'], {'count': 0, 'last': None})
            entry['count'] += row['n']
            entry['last'] = max(filter(None, (entry['last'], row['last'])), default=None)
        spans = self._rows("SELECT name, status, duration_ms, session_id, trace_id, end_ns FROM events "
                           "WHERE kind='span' AND ts >= ? ORDER BY ts DESC LIMIT 5000", (since_ns,))
        families = {}
        for span in spans:
            fam = families.setdefault(_family(span['name']), {'spans': 0, 'errors': 0, 'total_ms': 0.0})
            fam['spans'] += 1
            fam['errors'] += span['status'] == 'ERROR'
            fam['total_ms'] += span['duration_ms'] or 0
        errors = [{'name': s['name'], 'session_id': s['session_id'], 'trace_id': s['trace_id'], 'end_ns': s['end_ns']}
                  for s in spans if s['status'] == 'ERROR'][:10]
        return {'stores': stores, 'window_hours': hours, 'counts': counts, 'families': families,
                'sessions': len({s['session_id'] for s in spans if s['session_id']}),
                'traces': len({s['trace_id'] for s in spans if s['trace_id']}), 'recent_errors': errors}

    def session(self, session_id):
        spans = self._rows("SELECT name, status, duration_ms, start_ns, end_ns, trace_id, span_id, parent_span_id, data FROM events "
                           "WHERE kind='span' AND session_id = ? ORDER BY start_ns LIMIT 2000", (session_id,))
        result = {'session_id': session_id, 'spans': len(spans), 'errors': 0, 'traces': len({s['trace_id'] for s in spans}),
                  'llm_calls': 0, 'tool_calls': 0, 'tokens': None, 'cost_usd': None, 'models': [], 'tools': {}, 'slowest': []}
        models = set()
        for span in spans:
            try:
                attrs = json.loads(span['data']).get('attributes') or {}
            except (ValueError, AttributeError):
                attrs = {}
            fam = _family(span['name'])
            result['errors'] += span['status'] == 'ERROR'
            if fam == 'llm':
                result['llm_calls'] += 1
                tokens = _first(attrs, _TOKEN_KEYS)
                if isinstance(tokens, (int, float)):
                    result['tokens'] = (result['tokens'] or 0) + tokens
            if fam == 'tool':
                result['tool_calls'] += 1
                tool = (span['name'] or '').split('.', 1)[-1]
                result['tools'][tool] = result['tools'].get(tool, 0) + 1
            cost = _first(attrs, _COST_KEYS)
            if isinstance(cost, (int, float)):
                result['cost_usd'] = (result['cost_usd'] or 0) + cost
            model = _first(attrs, _MODEL_KEYS)
            if model:
                models.add(str(model))
        result['models'] = sorted(models)
        result['trace_list'] = self._traces(spans)
        result['slowest'] = [{'name': s['name'], 'duration_ms': s['duration_ms'], 'status': s['status']}
                             for s in sorted(spans, key=lambda s: -(s['duration_ms'] or 0))[:5]]
        return result

    @staticmethod
    def _traces(spans, limit=50):
        by_trace = {}
        for span in spans:
            by_trace.setdefault(span['trace_id'], []).append(span)
        traces = []
        for trace_id, members in by_trace.items():
            ids = {s['span_id'] for s in members}
            children = {}
            for span in members:
                parent = span['parent_span_id'] if span['parent_span_id'] in ids else None
                children.setdefault(parent, []).append(span)
            ordered = []
            def walk(parent, depth):
                for span in sorted(children.get(parent, []), key=lambda s: s['start_ns'] or 0):
                    ordered.append({'name': span['name'], 'status': span['status'], 'depth': min(depth, 8),
                                    'duration_ms': span['duration_ms'], 'start_ns': span['start_ns']})
                    if len(ordered) < 300:
                        walk(span['span_id'], depth + 1)
            walk(None, 0)
            starts = [s['start_ns'] for s in members if s['start_ns']]
            ends = [s['end_ns'] for s in members if s['end_ns']]
            traces.append({'trace_id': trace_id, 'root': ordered[0]['name'] if ordered else None, 'spans': len(members),
                           'errors': sum(s['status'] == 'ERROR' for s in members),
                           'start_ns': min(starts) if starts else None,
                           'duration_ms': (max(ends) - min(starts)) / 1e6 if starts and ends else None, 'tree': ordered})
        traces.sort(key=lambda t: t['start_ns'] or 0, reverse=True)
        return traces[:limit]
