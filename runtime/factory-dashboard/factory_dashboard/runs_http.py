"""Run-board routes: an aggregated overview, per-board detail and board-scoped lifecycle operations."""
from .runs_service import OPERATIONS


def route_runs(handler, path):
    from .http_server import RequestError
    runs = getattr(handler.server, 'runs', None)
    if runs is None:
        raise RequestError(404, 'Run boards are not enabled')
    parts = path.strip('/').split('/')
    if handler.command == 'GET':
        if parts == ['api', 'runs']:
            return handler._send(200, runs.overview())
        if len(parts) == 3 and parts[:2] == ['api', 'runs']:
            return handler._send(200, runs.board(parts[2]))
    elif handler.command == 'POST' and len(parts) == 4 and parts[:2] == ['api', 'runs'] and parts[3] in OPERATIONS:
        body = handler._body()  # same local-origin and token protection as every other mutation
        if set(body) - {'reason'}:
            raise RequestError(400, 'Only a reason may accompany a run operation')
        reason = body.get('reason', '')
        if not isinstance(reason, str):
            raise RequestError(400, 'Reason must be text')
        return handler._send(200, runs.operate(parts[2], parts[3], reason))
    raise RequestError(404, 'Run route not found')
