"""Read-only checksums of policy state; never exports task or prompt content."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import quote


def inspect(path):
    with sqlite3.connect('file:'+quote(str(path.resolve()))+'?mode=ro',uri=True) as conn:
        conn.execute('BEGIN')
        tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        hashes={}
        for name in ('factory_defaults','factory_snapshots','factory_tasks','factory_submissions',
                     'factory_activation','factory_cancelled','factory_workflow_defaults','factory_workflow_activation'):
            if name in tables:
                rows=conn.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()
                hashes[name]=dict(count=len(rows),sha256=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest())
        revisions={f'{tid}:{revision}':hashlib.sha256(document.encode()).hexdigest()
            for tid,revision,document in conn.execute('SELECT template_id,revision,document FROM factory_workflow_revisions')}
        heads=[dict(id=row[0],revision=row[1],archived=bool(row[2]))
            for row in conn.execute('SELECT id,revision,archived FROM factory_workflow_templates ORDER BY rowid')]
    return dict(tables=hashes,revisions=revisions,heads=heads)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings-db',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--before',type=Path)
    args=parser.parse_args()
    result=inspect(args.settings_db)
    if args.before:
        before=json.loads(args.before.read_text())
        assert result['tables']==before['tables'],'Unrelated policy state changed'
        assert all(result['revisions'].get(k)==v for k,v in before['revisions'].items()),'Historical revision changed'
        result['previous_state_preserved']=True
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(f'{args.output}: state inspected')
