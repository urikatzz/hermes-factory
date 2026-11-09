"""Install a hash-pinned workflow release; leave activation to verified follow-up."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    release=json.loads(args.manifest.read_text());home=Path(release['home'])
    for row in release['files']:
        source=Path(row['source']);destination=Path(row['destination'])
        destination.relative_to(home)
        if digest(source)!=row['source_sha256']:
            raise RuntimeError('Source changed after packaging: '+str(source))
        if digest(destination)!=row['expected_sha256']:
            raise RuntimeError('Installed file changed after preflight: '+str(destination))
    with sqlite3.connect('file:'+str(home/'kanban.db')+'?mode=ro',uri=True) as conn:
        if conn.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]:
            raise RuntimeError('Active workers must finish before this release is installed')
    if not args.apply:
        print(json.dumps({'ready':True,'files':len(release['files']),'homes':len(release['homes'])}));return
    backup=home/'backups'/('factory-workflows-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,mode=0o700)
    pause=home/'ESTOP';created_pause=not pause.exists()
    if created_pause:
        pause.write_text(json.dumps({'reason':'Installing Factory workflow templates','engaged_at':datetime.now(timezone.utc).isoformat()}))
    # Recheck after the new-work pause, before writing any source or state.
    with sqlite3.connect(home/'kanban.db') as conn:
        if conn.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]:
            if created_pause:pause.unlink()
            raise RuntimeError('A worker started during preflight; installation deferred')
    installed=[]
    for row in release['files']:
        destination=Path(row['destination']);saved=backup/destination.relative_to(home)
        if destination.exists():
            saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(destination,saved)
        installed.append({'path':str(destination),'existed':destination.exists()})
    # SQLite backup includes WAL content and preserves every historical snapshot.
    for relative in ('kanban.db','state/factory/task-settings.db'):
        source=home/relative;saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True) as src,sqlite3.connect(saved) as dst:
            src.backup(dst)
    (backup/'manifest.json').write_text(json.dumps({'files':installed,'created_pause':created_pause,'release':release},indent=2))
    for row in release['files']:
        destination=Path(row['destination']);destination.parent.mkdir(parents=True,exist_ok=True)
        temporary=destination.with_name(destination.name+'.factory-workflows-new')
        shutil.copy2(row['source'],temporary);os.replace(temporary,destination)
    sys.path.insert(0,release['source_roots']['dashboard'])
    from factory_dashboard.task_settings_store import TaskSettingsStore
    from factory_dashboard.workflow_capture import WorkflowCapture
    from factory_dashboard.workflow_templates import WorkflowTemplates
    store=TaskSettingsStore(home/'state/factory/task-settings.db',create=False)
    capture=WorkflowCapture(store,WorkflowTemplates(store));capture.initialize()
    with store._connect() as conn:
        if capture.enabled(conn):raise RuntimeError('Unexpected existing workflow activation; leave pause for inspection')
    for row in release['files']:
        if digest(Path(row['destination']))!=row['source_sha256']:
            raise RuntimeError('Installed checksum mismatch')
    print(json.dumps({'backup':str(backup),'files':len(installed),'homes':len(release['homes']),'workflows_enabled':False,'created_pause':created_pause}))


if __name__=='__main__':main()
