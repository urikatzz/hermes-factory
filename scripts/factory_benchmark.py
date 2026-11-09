#!/usr/bin/env python3
"""Prepare pinned benchmark inputs and report operator-imported results offline."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from factory_ecc.files import canonical, contained, private_write
from factory_ecc.graders import prepare_grading
from factory_ecc.reporting import summarize, render_markdown
from factory_ecc.results import load_trials
from factory_ecc.tasksets import load_taskset, prepare_case


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('taskset','prepare','grading','report'):
        command=commands.add_parser(name)
        command.add_argument('--taskset',required=True,type=Path)
        if name in ('prepare','grading'):
            command.add_argument('--case',required=True)
        if name != 'taskset':
            command.add_argument('--output',required=True,type=Path)
        if name=='grading':
            command.add_argument('--candidate',required=True,type=Path)
        if name=='report':
            command.add_argument('--results',required=True,type=Path)
            command.add_argument('--evidence-root',required=True,type=Path)
    args=parser.parse_args()
    try:
        taskset=load_taskset(args.taskset)
        if args.command=='taskset':
            print(json.dumps({k:v for k,v in taskset.items() if k!='root'},indent=2,sort_keys=True))
        elif args.command=='prepare':
            print(canonical(prepare_case(taskset,args.case,args.output)))
        elif args.command=='grading':
            print(canonical(prepare_grading(taskset,args.case,args.candidate,args.output)))
        else:
            trials=load_trials(taskset,args.results,args.evidence_root)
            report=summarize(taskset,trials)
            markdown=render_markdown(report)
            paths=[Path(str(args.output)+extension) for extension in ('.json','.md')]
            protected={args.results.resolve(),(taskset['root']/'taskset.json').resolve()}
            protected.update(contained(taskset['root'],p).resolve() for p in taskset['files'])
            candidates=[]
            for trial in trials:
                if trial['candidate_source'] is not None:
                    candidates.append(contained(args.evidence_root,trial['candidate_source']).resolve())
                for reference in trial['evidence'].values():
                    if reference is not None:
                        protected.add(contained(args.evidence_root,reference['path']).resolve())
            if any(path.is_symlink() or path.resolve() in protected
                   or any(path.resolve().is_relative_to(source) for source in candidates) for path in paths):
                raise ValueError('Refusing output collision with results, evidence, candidate source or taskset')
            # Validate and render both outputs before replacing either file.
            json_text=json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n'
            for path,content in zip(paths,(json_text,markdown)):
                private_write(path,content)
            print(f'{paths[0]}\n{paths[1]}')
        return 0
    except (ValueError,OSError) as exc:
        parser.exit(2,f'{exc}\n')


if __name__=='__main__':
    raise SystemExit(main())
