#!/usr/bin/env python3
"""Preview/apply Factory ECC guidance or restore one migration receipt."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_ecc.files import read_json, write_json
from factory_ecc.migration import build_preview, apply_preview, rollback_receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dashboard-source', required=True, type=Path)
    parser.add_argument('--settings-db', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument('--apply-preview', type=Path)
    operation.add_argument('--rollback-receipt', type=Path)
    parser.add_argument('--receipt-dir', type=Path)
    args = parser.parse_args()
    if args.apply_preview and not args.receipt_dir:
        parser.error('--apply-preview requires a new --receipt-dir')
    sys.path.insert(0, str(args.dashboard_source.resolve(strict=True)))
    from factory_dashboard.task_settings_store import TaskSettingsStore
    from factory_dashboard.workflow_templates import WorkflowTemplates
    from dataclasses import asdict
    try:
        templates = WorkflowTemplates(TaskSettingsStore(args.settings_db, create=False))
        if args.apply_preview:
            result = apply_preview(templates, read_json(args.apply_preview), args.receipt_dir)
        elif args.rollback_receipt:
            result = asdict(rollback_receipt(templates, read_json(args.rollback_receipt)))
        else:
            result = build_preview(templates)
        write_json(args.output, result)
        print(f'{args.output}: {result.get("status", "written")}')
        return 0 if result.get('status', 'complete') == 'complete' else 2
    except (ValueError, OSError) as exc:
        parser.exit(2, f'{exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
