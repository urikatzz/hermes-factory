# SYNTHETIC — report mechanics only; no model evaluation

Taskset: `706bca2e5768f19c868b9f02f31c6e83e0b62b496b78c899a900d0dc3a881966`. Imported trials: 6.

| Variant | Imported | First attempt (known history) | Eventual (success + failed) | Blocked | Incomplete | Missing evidence |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 3 | 3/3 (100%) | 3/3 (100%) | 0 | 0 | 0 |
| candidate | 3 | 2/2 (100%) | 2/2 (100%) | 1 | 0 | 0 |

Case coverage counts imported trials; unrun cases are shown as zero, not passing.

| Variant | Case | Imported | Success | Failed | Blocked | Incomplete |
|---|---|---:|---:|---:|---:|---:|
| baseline | bug | 1 | 1 | 0 | 0 | 0 |
| baseline | feature | 1 | 1 | 0 | 0 | 0 |
| baseline | chore | 1 | 1 | 0 | 0 | 0 |
| candidate | bug | 1 | 1 | 0 | 0 | 0 |
| candidate | feature | 1 | 0 | 0 | 1 | 0 |
| candidate | chore | 1 | 1 | 0 | 0 | 0 |

| Variant | Repairs total / known trials | Median seconds / known trials |
|---|---:|---:|
| baseline | 0 / 3 | 12.5 / 3 |
| candidate | 0 / 3 | 12.5 / 3 |

| Scope | Actual USD (known sessions) | Estimates USD (known sessions) | Included sessions | Trials without sessions |
|---|---:|---:|---:|---:|
| Overall | unknown (0) | unknown (0) | 0 | 6 |
| baseline | unknown (0) | unknown (0) | 0 | 3 |
| candidate | unknown (0) | unknown (0) | 0 | 3 |

Shared sessions are counted once overall and excluded from variant costs: none

Token counters are separate in the JSON report; no combined token total is invented.

Limitations:

- Operator-imported evidence is not independently authenticated.
- Functional graders share a process with candidate code; review grading provenance.
- No statistical superiority is established by this report.
- Unknown costs and unlinked coordinator/infrastructure usage are not zero.
