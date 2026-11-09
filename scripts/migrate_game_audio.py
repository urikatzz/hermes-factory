#!/usr/bin/env python3
"""Add the Game Audio roles, catalog entries, template and audio type default, or reverse it. Idempotent."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_game_audio.migration import Migration, write_receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dashboard-source', required=True, type=Path,
                        help='factory-dashboard folder whose factory_dashboard package has the audio type')
    parser.add_argument('--settings-db', required=True, type=Path, help='state/factory/task-settings.db')
    parser.add_argument('--catalog', required=True, type=Path, help='state/factory/model-catalog.json')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='print what --apply would change; write nothing')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', action='store_true',
                      help='remove the audio type default and archive Game Audio; role rows and catalog entries stay')
    parser.add_argument('--purge-template', action='store_true',
                        help='with --rollback: delete the Game Audio template rows (refused once any task used audio)')
    parser.add_argument('--receipt', type=Path, help='new JSON file recording what --apply/--rollback changed')
    args = parser.parse_args()
    if (args.apply or args.rollback) and not args.receipt:
        parser.error('--apply and --rollback require a new --receipt path')
    if args.purge_template and not args.rollback:
        parser.error('--purge-template requires --rollback')
    if args.receipt and args.receipt.exists():
        parser.error(f'{args.receipt} already exists')
    try:
        migration = Migration(args.dashboard_source, args.settings_db, args.catalog)
        if args.dry_run:
            result = migration.preview()
        elif args.apply:
            result = migration.apply()
        else:
            result = migration.rollback(args.purge_template)
    except (ValueError, OSError) as error:
        parser.exit(2, f'migrate_game_audio: {error}\n')
    if args.receipt:
        write_receipt(args.receipt, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
