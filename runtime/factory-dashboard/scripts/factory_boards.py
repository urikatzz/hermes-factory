#!/usr/bin/env python3
"""Inspect and operate Factory run boards: one dedicated Hermes board per factory run.

  factory_boards.py list [--all] [--json]
  factory_boards.py show BOARD [--json]
  factory_boards.py provision TICKET [--name N --project P --workflow W --project-dir D --branch B]
  factory_boards.py pause|resume|cancel|archive BOARD [--reason R]
  factory_boards.py bind-root BOARD ROOT
  factory_boards.py reset BOARD           (give a failed board a fresh provisioning budget)
  factory_boards.py resolve --db PATH [--label SLUG]   (what the Factory hooks decide for a board)

Use the Hermes venv python. The installed `factory-models` plugin must be active so lifecycle operations share its guard authority.
"""
import argparse
import importlib
import json
from pathlib import Path
import os
import sys


def hermes_home():
    return Path(os.environ.get('FACTORY_HERMES_HOME') or os.environ.get('HERMES_HOME') or Path.home() / '.hermes')


def plugin_settings(home):
    import yaml
    config = yaml.safe_load((home / 'config.yaml').read_text()) or {}
    entry = ((config.get('plugins') or {}).get('entries') or {}).get('factory-models') or {}
    settings = dict(entry.get('settings') or {})
    if not settings.get('board_path'):
        raise SystemExit('factory-models settings.board_path is not configured in ' + str(home / 'config.yaml'))
    return settings


def load(args):
    sys.path.insert(0, str(Path(args.hermes_source).resolve()))
    from hermes_cli import plugins
    plugins.discover_plugins()
    consumer = next((p for p in plugins.get_plugin_manager()._plugins.values() if p.manifest.name == 'factory-models' and p.enabled and not p.error), None)
    if not consumer or getattr(consumer.module, 'BOARD_CONTRACT_VERSION', 0) != 1:
        raise SystemExit('The installed factory-models plugin does not support run boards; sync the plugin first')
    package = consumer.module.__name__ + '.factory_dashboard.'
    registry_module = importlib.import_module(package + 'board_registry')
    boards_module = importlib.import_module(package + 'run_boards')
    settings = plugin_settings(hermes_home())
    resolver = registry_module.build_resolver(settings, create=True)
    return registry_module, boards_module, resolver


def table(rows):
    for row in rows:
        print('  '.join(str(cell) for cell in row))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--hermes-source', default=str(Path.home() / '.hermes/hermes-agent'))
    sub = parser.add_subparsers(dest='command', required=True)
    lst = sub.add_parser('list');lst.add_argument('--all', action='store_true');lst.add_argument('--json', action='store_true')
    show = sub.add_parser('show');show.add_argument('board');show.add_argument('--json', action='store_true')
    prov = sub.add_parser('provision');prov.add_argument('ticket')
    for name in ('name', 'project', 'workflow', 'project-dir', 'branch'):
        prov.add_argument('--' + name, default='')
    for name in ('pause', 'resume', 'cancel', 'archive'):
        op = sub.add_parser(name);op.add_argument('board');op.add_argument('--reason', default=name + ' by operator')
    tidy = sub.add_parser('archive-cards');tidy.add_argument('board');tidy.add_argument('cards', nargs='+')
    bind = sub.add_parser('bind-root');bind.add_argument('board');bind.add_argument('root')
    rst = sub.add_parser('reset');rst.add_argument('board')
    res = sub.add_parser('resolve');res.add_argument('--db', required=True);res.add_argument('--label')
    args = parser.parse_args(argv)
    registry_module, boards_module, resolver = load(args)
    registry = resolver.registry
    service = boards_module.RunBoards(registry)
    if args.command == 'list':
        statuses = None if args.all else registry_module.GOVERNED
        rows = [service.summary(b) for b in registry.list(statuses)]
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
        else:
            table([('BOARD', 'STATUS', 'PHASE', 'AWAITING', 'ROOT', 'TICKET')] + [(r['board_id'], r['status'], r['phase'] or '-', 'yes' if r['awaiting'] else '-', r['root_id'] or '-', r['ticket_id']) for r in rows])
    elif args.command == 'show':
        board = registry.get(args.board)
        if board is None:
            raise SystemExit('Unknown run board ' + args.board)
        print(json.dumps(service.summary(board), indent=2, default=str))
    elif args.command == 'provision':
        try:
            board = service.provision(args.ticket, name=args.name, project_id=args.project, workflow_id=args.workflow,
                                      project_dir=args.project_dir, branch=args.branch)
        except Exception as exc:  # machine-readable for the intake pump; never a traceback
            record = registry.by_ticket(args.ticket)
            print(json.dumps(dict(error=str(exc), status=record.status if record else 'unregistered')))
            raise SystemExit(2)
        print(json.dumps(dict(board=board.board_id, status=board.status)))
    elif args.command == 'bind-root':
        print(json.dumps(dict(board=args.board, root=registry.set_root(args.board, args.root).root_id)))
    elif args.command in ('pause', 'resume', 'cancel', 'archive'):
        method = getattr(service, args.command)
        result = method(args.board) if args.command in ('resume', 'archive') else method(args.board, args.reason)
        print(json.dumps(result, default=str))
    elif args.command == 'archive-cards':
        print(json.dumps(service.archive_replaced(args.board, args.cards)))
    elif args.command == 'reset':
        print(registry.reset_failed(args.board).status)
    elif args.command == 'resolve':
        found = resolver.resolve(args.db, args.label)
        print(json.dumps(found.public() if found else None, indent=2, default=str))


if __name__ == '__main__':
    main()
