#!/usr/bin/env python3
"""Inspect or apply a board-specific immutable Factory settings migration."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_dashboard.migration_sources import migration_for

parser = argparse.ArgumentParser(description=__doc__)
for name in ('board-db', 'hermes-home', 'catalog', 'settings-db'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--board-id', default='default')
parser.add_argument('--old-policy-db', type=Path)
parser.add_argument('--apply-digest')
args = parser.parse_args()
migration = migration_for(args.board_db, args.board_id, args.hermes_home, args.catalog, args.settings_db, args.old_policy_db)
result = migration.apply(args.apply_digest) if args.apply_digest else migration.inspect()
print(json.dumps(result, indent=2))
