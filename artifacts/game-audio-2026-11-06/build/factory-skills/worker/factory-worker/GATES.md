# Gate contract (lint, format, typecheck, test, build)

The deterministic gate is the cheapest reviewer: it costs no tokens and runs identically every time. Every factory job has ONE gate command; the verifier runs it first and its exit code decides before any judgement.

## The gate command
- Node/TS/web: `npm run factory:check` = format check, lint, typecheck, test, build, in that order, failing on the first non-zero exit. `package.json` defines the scripts `format:check`, `lint`, `typecheck`, `test`, `build`, and `factory:check` chains them with `&&`.
- Python: `.factory/check.sh` running `ruff format --check`, `ruff check`, `mypy` (if the project uses types), `pytest`.
- Unity / C#: `.factory/check.sh` that runs the project's own batchmode compile and EditMode tests only when the Unity CLI exists on the machine; otherwise the AC is `unverified:environment` and goes to the human (never silently skipped).
- Anything else: a single script `.factory/check.sh`, exit 0 = pass.

## Header GATE lines (registered repos)
A root header may carry lines `GATE: <path prefix> => <command>`, run from the repo root of the frozen copy. The verifier runs every GATE whose prefix matches a file in the writer's `changed_files` (a prefix `*` always applies), in addition to the generic gate below, and records each as a check. A failing GATE command is a FAIL like any failing check. The developer runs the same commands before completing. A command that cannot run on this machine (missing tool, Docker down) is `blocked_tools` + `unverified:environment`, never a silent skip.

## WRITER_GATE lines (checks that need the full checkout)
Some checks cannot run on the verifier's manifest copy (for example Unity compile and tests need the whole project). The header lists them as `WRITER_GATE: <path prefix> => <command>`. The developer runs each matching command in PROJECT_DIR before completing and reports its one-line result in `checks_run`; the publisher then re-runs them independently on the host before any PR is opened, so a failure there blocks publishing. Unity: always `sh $HOME/.hermes/scripts/unity_gate.sh . EditMode` (official Unity CLI, one editor at a time, cloned Library cache); never call the Unity editor binary directly.

## Rules by PROJECT_MODE
- new: the gate is mandatory. The PLAN's Acceptance Criteria include "AC-GATE: the gate command exists, exits 0 on a clean install, and covers format, lint, typecheck (if the language has one), tests and build". The architect resolves tool versions from the registry (`npm view '<pkg>' version`), checks each against OSV, and pins exact versions. Standard tools: ESLint (flat config) + Prettier + TypeScript `--noEmit` + the project's test runner.
- existing: wrap what the repository already has. Never impose a new linter, formatter or rule set on an existing codebase. `factory:check` (or `.factory/check.sh`) only chains the project's existing scripts. If the project has no lint at all, say so in `residual_risk` and `followups`; it is not a blocker and not a reason to add tooling the plan does not name.
- Gate scripts are part of the deliverable: list them in the manifest include list.

## Verifier and developer duties
- developer: run the gate before completing; record it in `checks_run` / `failed_checks`. Never edit lint config or disable rules to make the gate pass; fix the code.
- verifier: run the gate on the frozen copy right after the clean install and record cmd, exit and summary. For a new project, a missing or non-zero gate is verdict FAIL with finding `F<n>|HIGH|AC-GATE|-|<what failed>`. For an existing project, a missing gate script is a MEDIUM finding only if the repository has lint/test scripts that the gate could chain.
