#!/usr/bin/env python3
"""Serve a local Factory timeline; model settings are staged until integration activation."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from factory_dashboard.collector import SnapshotCollector
from factory_dashboard.models import SourcePaths
from factory_dashboard.report import ReportBuilder
from factory_dashboard.policy_store import PolicyStore
from factory_dashboard.model_catalog import ModelCatalog
from factory_dashboard.live_service import LiveService
from factory_dashboard.http_server import create_server
from factory_dashboard.factory_model_resolver import board_key


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-settings-source',type=Path,help='Enable live profile model/effort writes using this Hermes checkout')
    parser.add_argument('--settings-db',type=Path,help='Immutable Factory snapshot store; disables historical/profile edits')
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--policy-db',type=Path,required=True)
    parser.add_argument('--catalog',type=Path)
    parser.add_argument('--port',type=int,default=4610)
    parser.add_argument('--board-db',type=Path)
    parser.add_argument('--board-id',default='default')
    parser.add_argument('--hermes-home',type=Path)
    parser.add_argument('--published-state',type=Path)
    parser.add_argument('--evidence-root',type=Path)
    parser.add_argument('--registry-db',type=Path,help='Run-board registry (default: board-registry.db beside --settings-db)')
    args=parser.parse_args()
    if args.demo:
        from factory_dashboard.demo import DemoCollector, DemoReportBuilder, demo_catalog
        collector=DemoCollector();builder=DemoReportBuilder(ReportBuilder());catalog=ModelCatalog(demo_catalog());identity='demo'
    else:
        if not all((args.board_db,args.hermes_home,args.catalog)):
            parser.error('--board-db, --hermes-home and --catalog are required without --demo')
        if args.policy_db.resolve() in {args.board_db.resolve(),args.catalog.resolve()}:
            parser.error('Policy database must be separate from source files')
        collector=SnapshotCollector(SourcePaths(args.board_db,args.board_id,args.hermes_home,args.published_state,args.evidence_root))
        builder=ReportBuilder();catalog=ModelCatalog.from_file(args.catalog);identity=board_key(args.board_db,args.board_id)
    service=LiveService(collector,builder,PolicyStore(args.policy_db),catalog,identity)
    if args.settings_db:
        if args.demo or not args.profile_settings_source:
            parser.error('Snapshot mode requires a board and --profile-settings-source')
        sys.path.insert(0,str(args.profile_settings_source.resolve()))
        from hermes_cli import kanban_db, kanban_db_connect
        from factory_dashboard.task_settings_store import TaskSettingsStore
        from factory_dashboard.hermes_intake import HermesIntake
        from factory_dashboard.task_submission import TaskSubmissionService
        from factory_dashboard.snapshot_service import SnapshotService
        from factory_dashboard.model_policy import ModelSelection
        store=TaskSettingsStore(args.settings_db,create=False)
        intake=HermesIntake(args.board_db,args.board_id,args.hermes_home/"state/factory/repos.json",kanban_db.create_task,kanban_db_connect.connect)
        def validate_roles(roles):
            for role,value in roles.items():
                catalog.validate(ModelSelection(value.provider,value.model),(role,))
        submissions=TaskSubmissionService(store,intake,identity,validate_roles)
        service=SnapshotService(service,store,catalog,identity,submissions,intake)
        from factory_dashboard.workflow_runtime import compose_workflows, workflow_readiness
        service=compose_workflows(service,store,identity,args.board_db,workflow_readiness)
    elif args.profile_settings_source:
        if args.demo:
            parser.error('Live profile settings cannot be enabled in demo mode')
        sys.path.insert(0,str(args.profile_settings_source.resolve()))
        import yaml
        from hermes_cli.config import atomic_config_replace
        from hermes_constants import VALID_REASONING_EFFORTS
        from factory_dashboard.profile_settings import ProfileSettings
        from factory_dashboard.profile_service import ProfileService
        settings=ProfileSettings(args.hermes_home,catalog,yaml.safe_load,atomic_config_replace,('none',*VALID_REASONING_EFFORTS))
        service=ProfileService(service,settings)
    service.initialize_defaults()
    server=create_server(service,'127.0.0.1',args.port)
    if args.settings_db and not args.demo:
        # Every registered run board is listed and operable; the default board stays the timeline above.
        from factory_dashboard.board_registry import build_resolver
        from factory_dashboard.runs_service import RunsService
        resolver=build_resolver(dict(board_path=str(args.board_db),board_id=args.board_id,snapshot_path=str(args.settings_db),
                                     registry_path=str(args.registry_db) if args.registry_db else None),create=True)
        def collect(database,board_id,published):
            return SnapshotCollector(SourcePaths(database,board_id,args.hermes_home,published,args.evidence_root)).collect()
        server.runs=RunsService(resolver,args.hermes_home,evidence_root=args.evidence_root,collector_factory=collect,builder=ReportBuilder())
    if args.hermes_home:
        from factory_dashboard.otel_source import OtelSource
        server.otel=OtelSource(args.hermes_home)
    print(f'Factory timeline: http://127.0.0.1:{server.server_port}',flush=True)
    print('Preview configuration: live dispatch integration has not been activated.',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__=='__main__': main()
