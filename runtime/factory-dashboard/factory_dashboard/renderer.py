"""Embed local assets safely and publish owner-only report files atomically."""
import json
import os
from pathlib import Path
import tempfile

from .report import safe_url


class HtmlRenderer:
    def __init__(self, asset_root: Path):
        self._assets = asset_root

    def render(self, report: dict) -> str:
        def sanitized(value):
            if isinstance(value,dict):
                return {k:safe_url(v) if k=='url' else sanitized(v) for k,v in value.items()}
            if isinstance(value,(list,tuple)):return [sanitized(v) for v in value]
            return value
        data=json.dumps(sanitized(report),ensure_ascii=False,allow_nan=False)
        for original,escaped in (('&','\\u0026'),('<','\\u003c'),('>','\\u003e'),('\u2028','\\u2028'),('\u2029','\\u2029')):
            data=data.replace(original,escaped)
        page=(self._assets/'report.html').read_text()
        page=page.replace('@@CSS@@',(self._assets/'report.css').read_text())
        page=page.replace('@@JS@@',(self._assets/'formatters.js').read_text()+'\n'+(self._assets/'report.js').read_text())
        return page.replace('@@DATA@@',data)


def write_report(output_path: Path, content: str) -> None:
    output_path.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.factory-report-',dir=output_path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,output_path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
