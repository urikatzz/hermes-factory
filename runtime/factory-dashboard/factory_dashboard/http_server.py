"""Loopback-only report server with revisioned, authenticated configuration writes."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import unquote, urlsplit

from .collector import SourceReadError
from .model_policy import ConfigurationError, ModelSelection
from .policy_store import RevisionConflict

ASSETS = Path(__file__).parent / 'assets'
ASSET_TYPES = {'live.js':'text/javascript', 'timeline.js':'text/javascript', 'timeline.css':'text/css', 'formatters.js':'text/javascript', 'task_forms.js':'text/javascript', 'workflow_forms.js':'text/javascript'}


class RequestError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class FactoryHandler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass

    def _send(self, status, data, content_type='application/json'):
        body = json.dumps(data, allow_nan=False).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type',content_type + '; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if self.headers.get('Origin') not in allowed or not secrets.compare_digest(self.headers.get('X-Factory-Token',''),self.server.token):
            raise RequestError(403,'Open this dashboard locally before saving')
        if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
            raise RequestError(415,'JSON is required')
        if self.headers.get('Transfer-Encoding'):
            raise RequestError(400,'Chunked requests are not accepted')
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: raise RequestError(400,'Invalid request length')
        if length < 1 or length > 98304:
            raise RequestError(413,'Request exceeds permitted size')
        try:
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValueError()
            return body
        except (ValueError,UnicodeError):
            raise RequestError(400,'Invalid JSON object')

    def _route(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
            raise RequestError(403,'Local host required')
        path=unquote(urlsplit(self.path).path)
        service=self.server.service
        if path.startswith(('/api/workflows','/api/workflow-defaults')) and hasattr(service,'workflows'):
            from .workflow_http import route_workflows
            return route_workflows(self,path)
        if self.command == 'GET':
            if path == '/':
                page=(ASSETS/'live.html').read_text().replace('@@TOKEN@@',self.server.token)
                return self._send(200,page.encode(),'text/html')
            if path.removeprefix('/assets/') in ASSET_TYPES and path.startswith('/assets/'):
                name=path.removeprefix('/assets/')
                return self._send(200,(ASSETS/name).read_bytes(),ASSET_TYPES[name])
            otel=getattr(self.server,'otel',None)
            if otel is not None:
                if path == '/api/otel': return self._send(200,otel.summary())
                if path.startswith('/api/otel/sessions/'): return self._send(200,otel.session(path.removeprefix('/api/otel/sessions/')))
            getters={'/api/report':service.report,'/api/configuration':service.configuration,
                     '/api/models':lambda:service.configuration()['role_choices']}
            if hasattr(service, 'defaults'):
                getters.update({'/api/defaults': service.defaults, '/api/projects': service.projects})
                if path.startswith('/api/submissions/'):
                    return self._send(200, service.submission_status(path.removeprefix('/api/submissions/')))
            if path in getters: return self._send(200,getters[path]())
        elif self.command == 'POST' and hasattr(service, 'submit'):
            body = self._body()
            parts = path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'submissions'] and parts[3] == 'cancel':
                return self._send(200, service.cancel_submission(parts[2]))
            if path == '/api/submissions/preview':
                return self._send(200, service.preview_submission(body))
            if path == '/api/submissions':
                return self._send(202, service.submit(body))
        elif self.command in ('PUT','DELETE'):
            body=self._body()
            parts=path.strip('/').split('/')
            try:
                revision=body['revision']
                selection=None if self.command == 'DELETE' else ModelSelection(**body['selection'])
            except (KeyError,TypeError): raise RequestError(400,'Selection and revision are required')
            if len(parts)==3 and parts[:2]==['api','profiles'] and self.command=='PUT' and hasattr(service,'save_profile'):
                return self._send(200,service.save_profile(parts[2],selection,body.get('effort'),revision))
            if len(parts)==3 and parts[:2]==['api','defaults'] and self.command=='PUT':
                if hasattr(service, 'defaults'):
                    return self._send(200, service.save_default(parts[2], selection, revision, body.get('effort')))
                return self._send(200,service.save_default(parts[2],selection,revision))
            if len(parts)==4 and parts[:2]==['api','tasks'] and parts[3]=='model':
                return self._send(200,service.save_override(parts[2],selection,revision))
        raise RequestError(404,'Not found')

    def _handle(self):
        try: self._route()
        except RequestError as error: self._send(error.status,{'error':error.message})
        except RevisionConflict as error: self._send(409,{'error':str(error)})
        except ConfigurationError as error: self._send(400,{'error':str(error)})
        except (SourceReadError,sqlite3.Error,OSError): self._send(503,{'error':'Source unavailable; previous configuration is preserved. Check local source access.'})
        except (ValueError,TypeError): self._send(400,{'error':'Invalid request or source data'})

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle


def create_server(service, host: str, port: int):
    if host != '127.0.0.1':
        raise ValueError('Bind to 127.0.0.1 only')
    server=ThreadingHTTPServer((host,port),FactoryHandler)
    server.service=service
    server.token=secrets.token_hex(32)
    return server
