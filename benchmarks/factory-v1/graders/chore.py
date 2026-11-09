"""Trusted fixture checks. Run only in an approved disposable sandbox.

This simple checker shares a Python process with candidate code. It is a functional
check, not a tamper-resistant judge. Operator review must attest grading provenance.
"""
import contextlib
import io
import json
from pathlib import Path
import runpy
import sys

job = json.loads(Path(sys.argv[2]).read_text())
results = {key: 'fail' for key in job['acceptance']}
def check(key, function):
    try:
        results[key] = 'pass' if function() else 'fail'
    except Exception:
        results[key] = 'fail'

try:
    with contextlib.redirect_stdout(io.StringIO()):
        module = runpy.run_path(str(Path(sys.argv[1]) / 'solution.py'))
    function = module['summarize']
    check('AC1', lambda: function([]) == {'count': 0, 'total': 0} and function([-2, 0.5, 3]) == {'count': 3, 'total': 1.5})
    check('AC2', lambda: function(iter([2, -1, 4])) == {'count': 3, 'total': 5})
except Exception:
    pass
print(json.dumps({**job, "schema": "factory-ecc-grades/v1", "ac_results": results}))
