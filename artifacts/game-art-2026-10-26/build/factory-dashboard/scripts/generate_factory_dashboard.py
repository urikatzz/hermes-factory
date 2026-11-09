#!/usr/bin/env python3
"""Generate an offline Factory dashboard from explicitly selected local records."""
import argparse
from pathlib import Path
import re
import sys

# Direct script execution works without an install or PYTHONPATH configuration.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from factory_dashboard.collector import SnapshotCollector, SourceReadError
from factory_dashboard.models import SourcePaths
from factory_dashboard.renderer import HtmlRenderer, write_report
from factory_dashboard.report import ReportBuilder


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board-db',type=Path,required=True)
    parser.add_argument('--board-id',required=True)
    parser.add_argument('--hermes-home',type=Path,required=True)
    parser.add_argument('--published-state',type=Path)
    parser.add_argument('--evidence-root',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',args.board_id):
            raise ValueError('Board ID must contain only letters, numbers, underscores or hyphens')
        output=args.output.resolve()
        home=args.hermes_home.resolve()
        inputs=[args.board_db,args.published_state]
        if any(p is not None and output==p.resolve() for p in inputs):
            raise ValueError('Output cannot replace an input source')
        if output.suffix.lower()!='.html':
            raise ValueError('Output must use the .html extension')
        if output==home or home in output.parents:
            raise ValueError('Choose an output outside the selected Hermes home')
        if args.evidence_root and (output==args.evidence_root.resolve() or args.evidence_root.resolve() in output.parents):
            raise ValueError('Choose an output outside the evidence root')
        paths=SourcePaths(args.board_db,args.board_id,args.hermes_home,args.published_state,args.evidence_root)
        snapshot=SnapshotCollector(paths).collect()
        report=ReportBuilder().build(snapshot)
        content=HtmlRenderer(ROOT/'factory_dashboard/assets').render(report)
        write_report(output,content)
        print(f'Generated {output} ({len(report["parents"])} parents, {len(report["unlinked_tasks"])} unlinked tasks, {len(report["warnings"])} warnings)')
        return 0
    except (SourceReadError,OSError,ValueError,TypeError) as error:
        print('Dashboard generation failed: '+str(error),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
