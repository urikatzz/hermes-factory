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

A command that needs the whole checkout is a writer gate wherever it was named (a GATE header, a card, a ticket note). The verifier runs it on the frozen copy only when that copy is a complete project; otherwise it does not run it, never records it in `failed_checks`, confirms the writer's `checks_run` result, and says in `residual_risk` that it was not run on the manifest. A failed check the verifier does record that is preexisting or has no fix stops the project for a human.

## Rules by PROJECT_MODE
- new: the gate is mandatory. The PLAN's Acceptance Criteria include "AC-GATE: the gate command exists, exits 0 on a clean install, and covers format, lint, typecheck (if the language has one), tests and build". The architect resolves tool versions from the registry (`npm view '<pkg>' version`), checks each against OSV, and pins exact versions. Standard tools: ESLint (flat config) + Prettier + TypeScript `--noEmit` + the project's test runner.
- existing: wrap what the repository already has. Never impose a new linter, formatter or rule set on an existing codebase. `factory:check` (or `.factory/check.sh`) only chains the project's existing scripts. If the project has no lint at all, say so in `residual_risk` and `followups`; it is not a blocker and not a reason to add tooling the plan does not name.
- Gate scripts are part of the deliverable: list them in the manifest include list.

## Verifier and developer duties
- developer: run the gate before completing; record it in `checks_run` / `failed_checks`. Never edit lint config or disable rules to make the gate pass; fix the code.
- verifier: run the gate on the frozen copy right after the clean install and record cmd, exit and summary. For a new project, a missing or non-zero gate is verdict FAIL with finding `F<n>|HIGH|AC-GATE|-|<what failed>`. For an existing project, a missing gate script is a MEDIUM finding only if the repository has lint/test scripts that the gate could chain.
- verifier, Unity scenes and builders: run every Unity command (gates and scene builders) in the foreground and record each exit code. "Builder reproducibility" or "run the builder twice" means the builder exits 0 on both runs and the EditMode and PlayMode tests still pass afterwards. Do not require byte-identical Unity scene or asset files: Unity re-serializes generated scenes, so a byte difference alone is at most a LOW note and never makes an AC `unverified:environment`.
- Tool incidents (all workers): when the safety guard refuses a command or a tool is missing, first get the same evidence another approved way. Record every refusal in metadata `tool_incidents` (`command`, `reason`, `required`, `resolved`, `alternative`, `affected_criteria`). Only a required tool that stayed unavailable is blocked work: list it in `blocked_tools` and mark the affected criteria `unverified:environment`. The controller decides from these fields; never hide or rephrase a refused command.
