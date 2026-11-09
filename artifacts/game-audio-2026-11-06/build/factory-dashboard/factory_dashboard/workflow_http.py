"""Workflow routes share the dashboard's local-host and mutation protections."""
from urllib.parse import urlsplit, parse_qs


def route_workflows(handler,path):
    from .http_server import RequestError
    service=handler.server.service.workflows
    parts=path.strip('/').split('/')
    method=handler.command
    if method=='GET':
        if parts==['api','workflows']:
            return handler._send(200,service.list())
        if len(parts)==3 and parts[:2]==['api','workflows']:
            query=parse_qs(urlsplit(handler.path).query)
            try: revision=int(query['revision'][0]) if 'revision' in query else None
            except ValueError: raise RequestError(400,'Invalid workflow revision')
            return handler._send(200,service.get(parts[2],revision))
    if method in ('POST','PUT'):
        body=handler._body()
        if parts==['api','workflows','preview'] and method=='POST':
            return handler._send(200,service.preview(body))
        if parts==['api','workflows'] and method=='POST':
            return handler._send(201,service.save(body,0))
        if len(parts)==3 and parts[:2]==['api','workflows'] and method=='PUT':
            if body.get('template_id')!=parts[2]:raise RequestError(400,'Workflow identity mismatch')
            return handler._send(200,service.save(body,body.get('revision')))
        if len(parts)==4 and parts[:2]==['api','workflows'] and parts[3] in ('archive','restore') and method=='POST':
            if set(body)!={'revision'}:raise RequestError(400,'Revision is required')
            action=service.archive if parts[3]=='archive' else service.restore
            return handler._send(200,action(parts[2],body['revision']))
        if len(parts)==3 and parts[:2]==['api','workflow-defaults'] and method=='PUT':
            if set(body)!={'template_id','revision'}:raise RequestError(400,'Template and revision are required')
            return handler._send(200,service.set_default(parts[2],body['template_id'],body['revision']))
    raise RequestError(404,'Workflow route not found')
