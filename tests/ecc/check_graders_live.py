"""Explicit no-model functional checks using the existing Factory sandbox runtime."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from factory_ecc.files import write_json
from factory_ecc.tasksets import load_taskset,prepare_case
from factory_ecc.graders import prepare_grading

REFERENCES={
    'bug': "def in_range(values, lower, upper):\n    return [value for value in values if lower <= value <= upper]\n",
    'feature': "def format_names(names, *, sort=False):\n    return ', '.join(sorted(names) if sort else names)\n",
    'chore': "def summarize(values):\n    count, total = 0, 0\n    for value in values:\n        count += 1\n        total += value\n    return {'count': count, 'total': total}\n",
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sandbox-source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.sandbox_source))
    from factory_sandbox.policy import AllowedDestination,AttemptIdentity,SandboxPolicy
    from factory_sandbox.runtime import DockerRuntime
    from factory_sandbox.workspace import WorkspaceStore
    image=json.loads(subprocess.check_output(['docker','image','inspect','hermes-factory-sandbox-probe:local']))[0]['Id']
    taskset=load_taskset(ROOT/'benchmarks/factory-v1')
    with tempfile.TemporaryDirectory(prefix='factory-ecc-graders-') as temporary:
        root=Path(temporary)
        source=root/'jobs';source.mkdir()
        for case in taskset['cases']:
            for mode in ('baseline','reference'):
                name=case['id']+'-'+mode
                worker=root/name
                prepare_case(taskset,case['id'],worker)
                if mode=='reference':
                    (worker/'source/solution.py').write_text(REFERENCES[case['id']])
                prepare_grading(taskset,case['id'],worker/'source',source/name)
        identity=AttemptIdentity(root/'profile','ecc-check','graders','1')
        workspace=WorkspaceStore(root/'workspaces').prepare(source,identity)
        runtime=DockerRuntime(root/'runtime')
        policy=SandboxPolicy('ecc-graders-v1',image,image,(AllowedDestination('example.com',443),),1,256,64,10)
        handle=runtime.start(identity,policy,workspace)
        checks=[]
        try:
            for case in taskset['cases']:
                for mode in ('baseline','reference'):
                    name=case['id']+'-'+mode
                    response=runtime.execute(handle,f'python3 {name}/trusted/grader.py {name}/candidate {name}/trusted/job.json')
                    if response['returncode']!=0:
                        raise RuntimeError(str(response))
                    grades=json.loads(response['output'])
                    expected=dict(AC1='pass',AC2='pass')
                    if mode=='baseline' and case['id']=='bug':expected=dict(AC1='fail',AC2='fail')
                    if mode=='baseline' and case['id']=='feature':expected['AC2']='fail'
                    if grades['ac_results']!=expected:
                        raise AssertionError((name,grades['ac_results'],expected))
                    checks.append(dict(case=case['id'],mode=mode,ac_results=grades['ac_results']))
        finally:
            runtime.remove(handle,allow_missing=True)
        write_json(args.output,dict(schema='factory-ecc-grader-check/v1',taskset_digest=taskset['digest'],
            image=image,model_calls=0,checks=checks,limitations='Functional grading only; shared-process checker is not tamper resistant.'))
        print(f'{len(checks)} sandbox grader checks passed; no model calls')


if __name__=='__main__':main()
