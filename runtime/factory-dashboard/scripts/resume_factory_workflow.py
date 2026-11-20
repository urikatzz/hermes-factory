#!/usr/bin/env python3
"""Retry a blocked workflow stage after an explicit human recovery decision."""
import argparse
import json
from contextlib import closing
import importlib
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-source',type=Path,required=True)
    parser.add_argument('--board-db',type=Path,required=True)
    parser.add_argument('--board',default='default')
    parser.add_argument('--new-project-root',type=Path,required=True)
    parser.add_argument('--root',required=True)
    parser.add_argument('--note',required=True)
    parser.add_argument('--reevaluate',action='store_true',help='re-judge the existing stage evidence under the current rules instead of retrying stages (also resumes a human_review stop)')
    parser.add_argument('--retry-stage',action='store_true',help='re-run only the stage the project stopped on (also resumes a human_review stop); earlier results stay as history, bounded per stage')
    parser.add_argument('--decision-file',type=Path,help='JSON human decision: {"waivers":[{"ac","path","source"?,"reason"}],"constraints":[{"preserve":[paths],"reason"}]}')
    args=parser.parse_args()
    sys.path.insert(0,str(args.hermes_source.resolve()))
    from hermes_cli import plugins,kanban_db,kanban_db_connect
    plugins.discover_plugins()
    consumer=next((p for p in plugins.get_plugin_manager()._plugins.values() if p.manifest.name=='factory-models' and p.enabled and not p.error),None)
    if not consumer or getattr(consumer.module,'WORKFLOW_CONTRACT_VERSION',0)!=1:
        parser.error('The installed workflow consumer must be active in this Hermes home')
    # Use the consumer's module namespace so its scoped controller authority is shared.
    package=consumer.module.__name__+'.factory_dashboard.'
    controller_type=importlib.import_module(package+'workflow_controller').WorkflowController
    state_type=importlib.import_module(package+'workflow_state').WorkflowState
    registry_module=importlib.import_module(package+'board_registry')
    # Only a governed board can be resumed, and a run board must be active: a paused, cancelled or failed run needs `factory_boards.py` first.
    import os, yaml
    home=Path(os.environ.get('FACTORY_HERMES_HOME') or os.environ.get('HERMES_HOME') or Path.home()/'.hermes')
    settings=(((yaml.safe_load((home/'config.yaml').read_text()) or {}).get('plugins') or {}).get('entries') or {}).get('factory-models',{}).get('settings') or {}
    if settings.get('board_path'):
        found=registry_module.build_resolver(settings).resolve(args.board_db,args.board)
        if found is None:
            parser.error('Board %s is not a Factory board; refusing to apply Factory recovery to it'%args.board)
        if found.is_run and found.status!='active':
            parser.error('Run board %s is %s; resume it with factory_boards.py first'%(found.board_id,found.status))
    controller=controller_type(kanban_db,state_type(),args.new_project_root)
    with closing(kanban_db_connect.connect(args.board_db,board=args.board)) as conn:
        decisions=json.loads(args.decision_file.read_text()) if args.decision_file else None
        if args.retry_stage:
            decisions={**(decisions or {}),'retry_stage':True}
        state=controller.resume(conn,args.root,args.note,decisions,args.reevaluate)
    print(f"{args.root}: {state['phase']}")


if __name__=='__main__':
    main()
