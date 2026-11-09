# Factory Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for native execution, or superpowers:subagent-driven-development if the user selects delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete one disposable Factory coding task with isolated terminal/file operations, enforced destination allowlisting, retained output, and verified cancellation.

**Architecture:** Build a standalone Hermes terminal-provider plugin named `factory_sandbox`, using the existing Docker environment through composition. A trusted supervisor prepares a filtered job workspace and an isolated network namespace; commands can reach only an allowlisting proxy. The Hermes process, model calls, Kanban database, and existing Unity/publishing automation remain host infrastructure outside the sandbox boundary.

**Tech Stack:** Python, Hermes terminal-provider API, Docker Desktop on the user's Mac, Linux nftables in a trusted namespace initializer, iron-proxy if the compatibility gate confirms its deployment contract. Use existing Python standard-library facilities and Hermes test tooling before adding dependencies.

**Spec:** `docs/superpowers/specs/2026-10-15-factory-sandbox-design.md` (approved by the user).

## Global Constraints

- Outbound network access must be limited to approved destinations and enforced independently of worker cooperation.
- The Hermes coordinator and model calls remain trusted host processes in this milestone.
- A sandbox startup failure blocks the stage; it never falls back to local execution.
- Do not expose the host home directory, Hermes state directories, SSH agent, credential stores, Docker socket, or other task workspaces.
- Drop network administration capabilities from the worker before running project code.
- On proxy failure or policy initialization failure, stop or block execution. Do not silently provide direct networking.
- The initial pilot uses a task that does not require Unity or other host-only tools.
- Rollback must not silently run an admitted sandbox-required task on the local backend.
- Preserve the existing manifest and review identity contracts.
- No commit or push without explicit user permission. Task boundaries are review checkpoints, not authorization to commit.
- Build in this workspace. Do not edit the installed Hermes checkout, installed profiles, proxy state, cron jobs, or live Factory scripts during implementation. Use an isolated `HERMES_HOME` for integration runs.
- Container resources and images are created only during explicit disposable runtime verification; record their ownership and remove only resources created by that verification.
- Native execution is recommended below; do not dispatch agents unless the user selects delegation.

## Review Focus

1. Proxy variables removed, custom TLS CA supplied, raw sockets, direct DNS, and IPv6 must not bypass filtering (Task 3).
2. A linked worktree, symlink, hardlink, special file, or archive traversal must not expose or overwrite host files (Task 2).
3. Concurrent jobs with the same profile and a restarted coordinator must not adopt another attempt's runtime (Tasks 3 and 5).
4. File tools, inherited terminal configuration, image startup hooks, and automatic mounts must not create host execution/credential paths (Tasks 1 and 4).
5. A dying proxy, partial initialization, cancellation, and output-import failure must preserve evidence and fail closed (Tasks 3 and 5).

## Repository and integration map

The inspected Hermes revision is `9e041a7428392b01b989ef9cecf46a5f96be12fc` in `/Users/example/.hermes/hermes-agent`. Pin integration documentation to that revision and repeat compatibility checks before supporting a different revision.

Existing interfaces to consume, not modify:

- `agent/terminal_env_provider.py::TerminalEnvironmentProvider`: `create_environment(*, cwd, timeout, task_id='default', image=None, container_config=None, **kwargs)`.
- `hermes_cli/plugins.py::PluginContext.register_terminal_environment_provider`.
- `tools/terminal_tool_backends.py::_build_plugin_env`: passes configured resource settings to providers.
- `tools/file_tools.py::_get_file_ops`: uses the selected terminal environment for shell file operations.
- `tools/environments/docker.py::DockerEnvironment`: command execution and teardown. Review its automatic skill mounts, environment forwarding, snapshots, reattachment, and recovery before composing it.
- `tools/terminal_tool_lifecycle.py`: actual idle/session cleanup path.
- `hermes_cli/kanban_db_dispatch.py::_default_spawn`: host worker launch and task/attempt context.
- Installed `factory-worker/scripts/fw.py`: manifest/snapshot contract; invoke a vetted read-only copy inside the sandbox where needed. Do not execute worker-supplied helper scripts on the host.

New files in this standalone workspace:

| Files | Responsibility |
| --- | --- |
| `plugin.yaml`, `__init__.py` | Plugin manifest and provider registration |
| `factory_sandbox/__init__.py`, `provider.py` | Existing Hermes provider interface and environment adapter |
| `factory_sandbox/policy.py` | Immutable policy and attempt identity validation |
| `factory_sandbox/workspace.py` | Safe filtered workspace preparation and result collection |
| `factory_sandbox/runtime.py` | Trusted Docker lifecycle, network initialization, cleanup |
| `factory_sandbox/evidence.py` | Atomic host-owned attempt records |
| `runtime/namespace.Dockerfile`, `runtime/init-network.sh` | Trusted namespace initialization with nftables |
| `runtime/worker.Dockerfile` | Minimal unprivileged worker image |
| `runtime/proxy/` | Pinned gateway deployment/configuration selected by Task 1 |
| `examples/pilot-policy.json`, `examples/pilot-profile.yaml` | Isolated pilot configuration; no credentials |
| `scripts/probe_compatibility.py`, `scripts/run_checks.sh`, `scripts/run_pilot.py` | Disposable verification and reproducible launch |
| `tests/test_policy.py`, `test_workspace.py`, `test_runtime.py`, `test_provider.py`, `test_evidence.py` | Focused behavior contracts |
| `tests/integration/test_network.py`, `test_hermes_routing.py`, `test_pilot.py` | Real Docker and Hermes execution checks |
| `docs/compatibility.md`, `docs/pilot-results.md` | Recorded evidence and operator instructions |

No core monkey patches, tool overrides, or model-visible new tools. Required service objects use constructor injection. Keep infrastructure and file handling separate from provider registration.

### Task 1: Establish the supported integration and network topology

**Files:** Create `scripts/probe_compatibility.py`, `docs/compatibility.md`. Inspect the existing interfaces listed above, their applicable `AGENTS.md` files, and Hermes's canonical test runner.

**Interfaces:** Produces a compatibility report with exact Hermes revision, Docker version, immutable image references, gateway pin, mount/environment behavior, namespace filtering behavior, and accepted provider lifecycle contract. The probe is disposable; it does not register a plugin or change a profile.

- [ ] Read the terminal-provider documentation, plugin manifest validation rules, Docker constructor and lifecycle code, file tool routing, and plugin/session identity behavior at the pinned revision.
- [ ] Inspect the existing iron-proxy protocol/configuration to establish whether it can run as a dedicated gateway with a narrow host/port allowlist, no model-provider credentials, and destination/address validation. Record the exact pinned artifact and config fields; do not infer these from `HTTPS_PROXY` support.
- [ ] Implement a disposable probe that creates uniquely labelled resources: a worker namespace, a gateway, a permitted HTTP/TLS fixture, and a denied fixture. Keep any test CA and all credentials synthetic.
- [ ] Establish the topology: worker joins the namespace container's network namespace; trusted initialization installs output filtering before project code starts; only the proxy IP/port is permitted. Worker has no `NET_ADMIN`/`NET_RAW`, no Docker socket, no host networking, no published ports, and runs unprivileged. Deny other IPv4/IPv6 output and DNS; ensure host gateway access is blocked. The gateway alone has upstream access.
- [ ] Run `python3 scripts/probe_compatibility.py --output /private/tmp/hermes-factory-sandbox-compatibility.json`. The output must include successful allowed HTTP/TLS, rejected proxy destination, rejected direct TCP/DNS/IPv6/host access, capability restrictions, and cleanup evidence. A missing Docker daemon is a failure with a setup message, not a passing skip.
- [ ] Inspect actual `DockerEnvironment` container mounts and environment with synthetic sentinels. Confirm that automatic skills/cache mounts, credential forwarding, recovery, and generated container names can be constrained to the spec without altering core.
- [ ] Record the exact compatible construction arguments and gateway config in `docs/compatibility.md`. If either gateway enforcement or safe Docker composition cannot be demonstrated, stop at this checkpoint and revise the design/plan with the evidence. Do not compensate with application-only guards, private-method monkey patches, or local fallback.

### Task 2: Implement immutable policy and safe job workspaces

**Files:** Create `factory_sandbox/{__init__,policy,workspace}.py`, `tests/test_policy.py`, `tests/test_workspace.py`, `examples/pilot-policy.json`, and `scripts/run_checks.sh`.

**Interfaces:**

- `AttemptIdentity(profile_home: Path, board: str, task_id: str, run_id: str)` is a frozen record; all fields are required and validated. Do not use bare `task_id` as a global key.
- `AllowedDestination(hostname: str, port: int)` and `SandboxPolicy(revision: str, worker_image: str, gateway_image: str, allowed_destinations: tuple[AllowedDestination, ...], cpu: float, memory_mb: int, pids_limit: int, command_timeout_seconds: int)` are frozen records. Image references must include digests. CPU, memory, PID, and timeout limits are positive.
- `load_policy(path: Path) -> SandboxPolicy` validates an administrator-owned JSON policy; absent/unknown fields or duplicate/conflicting destinations fail visibly. Pilot policy has no wildcards and no forwarded secrets. Exact resource values and image digests come from Task 1's measured fixture and recorded artifact identities.
- `WorkspaceStore(root: Path)` consumes supervisor-owned storage.
- `WorkspaceStore.prepare(source_root: Path, identity: AttemptIdentity) -> Path` copies regular source files into an owned attempt workspace, excludes Git metadata, credentials, and generated caches using the reviewed Factory exclusion contract.
- `WorkspaceStore.collect(workspace: Path, identity: AttemptIdentity) -> Path` creates a new immutable result directory plus manifest; it does not apply changes to a live repository.

- [ ] Add failing behavior checks: reject IP-literal/private/loopback destinations, wildcard hosts, malformed ports, missing image pins, nonpositive limits, and identity collisions across profiles/boards/runs. Validate policy is fixed for a live attempt even if the policy file changes later.
- [ ] Add failing workspace checks: ordinary source copied; linked `.git` file/common metadata excluded; credentials excluded; source symlinks, hardlinked files, FIFOs/devices, and escaping paths refused. Collect from a stopped container only; reject substituted roots or symlinked ancestors. Tests use temporary directories and synthetic credential sentinels.
- [ ] Implement policy and workspace interfaces. Copy file bytes into new files; never preserve source hardlinks. Validate paths at time of use with descriptor-relative/no-follow operations where supported. Stage results in a new owned directory and atomically publish only after validation; never extract an untrusted archive directly over a host directory.
- [ ] Add manifest/deletion behavior: record changed and removed source paths as data; preserve `.factory/include.txt`, `.factory/PLAN.md`, and manifest identities. Never execute hooks or commands found in returned files. Refuse concurrent collection while execution is active.
- [ ] Run `scripts/run_checks.sh unit policy workspace`; require all relevant behavior tests to pass. The wrapper must provide a documented isolated interpreter and run plugin checks through pytest without importing the live profile. When testing inside the Hermes checkout, use its `scripts/run_tests.sh` rather than bare pytest.

### Task 3: Implement runtime enforcement and ownership

**Files:** Create `factory_sandbox/runtime.py`, `runtime/namespace.Dockerfile`, `runtime/init-network.sh`, `runtime/worker.Dockerfile`, gateway files under `runtime/proxy/`, `tests/test_runtime.py`, and `tests/integration/test_network.py`.

**Interfaces:**

- `RuntimeHandle(identity: AttemptIdentity, workspace: Path, namespace_id: str, worker_id: str, gateway_id: str, policy_revision: str)` is a frozen record.
- `DockerRuntime.start(identity: AttemptIdentity, policy: SandboxPolicy, workspace: Path) -> RuntimeHandle` returns only after rules and gateway health are verified.
- `DockerRuntime.execute(handle: RuntimeHandle, command: str, cwd: str, timeout: int) -> dict` uses the existing Docker environment's command result contract, established in Task 1.
- `DockerRuntime.stop(handle: RuntimeHandle) -> None` terminates owned worker/project processes before output collection.
- `DockerRuntime.remove(handle: RuntimeHandle) -> None` idempotently deletes only this handle's verified owned resources after collection/evidence.

- [ ] Add failing lifecycle tests for partial startup, proxy loss, wrong attempt labels, stale/recycled resource identities, and cleanup called twice. Verify failure never calls a local execution backend.
- [ ] Implement the Task 1 topology. Use argument arrays for Docker control commands. Pass a minimal explicit environment to worker creation; ignore/reject arbitrary inherited Docker extra args, mounts, environment forwarding, shared-container settings, and image overrides. Never run worker-authored initialization scripts with trusted networking capabilities.
- [ ] Compose the existing `DockerEnvironment` only with the safe constructor arguments proven in Task 1. Bind only the owned workspace; force separate attempt identity and disable cross-process adoption/automatic recreation that bypasses fresh policy verification. Ensure no worker container executes its image entrypoint before network restrictions are ready; use only pinned, reviewed runtime images.
- [ ] Create the trusted namespace with filtering established before the worker starts. Bind proxy access to a fixed endpoint selected by the supervisor. Deny direct DNS and IPv6 bypasses; gateway resolution validates every resulting address, port, CONNECT request, redirect, and fresh connection. Package fixtures use local synthetic TLS endpoints; live registry domains are added only after a task's actual requirements are known.
- [ ] Add real network assertions: allow approved HTTP/TLS; deny unapproved hostname/port, direct IPv4/IPv6, private/loopback/metadata destinations, raw socket connection, custom CA, unset proxy variables, host gateway services, sibling jobs, and DNS rebinding/redirect to a private fixture. An unavailable IPv6 route is recorded separately from demonstrated firewall denial.
- [ ] Run `scripts/run_checks.sh unit runtime` and `scripts/run_checks.sh integration network`. Report blocked attempts, expected successful responses, effective capabilities, and owned-resource cleanup. Infrastructure absence must fail explicitly once this integration lane is requested.

### Task 4: Register the backend and prove real Hermes tool routing

**Files:** Create `plugin.yaml`, root `__init__.py`, `factory_sandbox/provider.py`, `examples/pilot-profile.yaml`, `tests/test_provider.py`, and `tests/integration/test_hermes_routing.py`.

**Interfaces:**

- `FactorySandboxProvider(TerminalEnvironmentProvider)` registers as `factory_sandbox`; it takes required supervisor dependencies through its constructor.
- Declare `is_remote=True`, `is_container=True`, `session_isolated_when_nonpersistent=True`, and `skip_container_guards=False`. Keep existing command approvals active.
- Implement the exact existing `create_environment(*, cwd, timeout, task_id='default', image=None, container_config=None, **kwargs)` interface; reject missing trusted attempt context. Unknown future kwargs may be ignored per Hermes's provider contract; known security-sensitive overrides must not weaken policy.
- Returned `FactorySandboxEnvironment` composes the runtime handle, satisfies `execute`/`cleanup` and the file/background interfaces identified in Task 1, and always uses `/workspace` as the project root.
- `register(ctx)` registers the provider and only lifecycle/guard hooks that have an actual pilot consumer. Policy and identity are read from profile-scoped trusted configuration/context, not from model-authored tool arguments.

- [ ] Add failing provider tests for scoped configuration, absent policy, missing attempt identity, Docker/gateway failure, wrong backend overrides, and container cwd mapping. Validate exact documented Hermes plugin manifest/schema instead of inventing config keys.
- [ ] Implement the provider and environment adapter using Tasks 2–3. Keep business decisions out of registration. Preserve profile/secret scope and isolate environment cache keys by attempt/session as supported by Hermes.
- [ ] Create an isolated pilot profile under a temporary `HERMES_HOME`: backend `factory_sandbox`, nonpersistent session containers, only `terminal`, `file`, and the needed Kanban tools. Keep delegation, `execute_code`, browser, arbitrary MCP, and other network/host execution tools disabled for this milestone. Assert the resolved tool surface, including automatically inherited core tools; if configuration cannot exclude a host execution path, block pilot admission and revise the integration.
- [ ] Exercise actual Hermes terminal and file handlers against the plugin: create/edit/read/search a file and run a background project process. Prove command and file tools share the assigned workspace/container and that absolute host paths, path overrides, and concurrent same-profile jobs cannot cross the boundary.
- [ ] Verify document/image reads, cache sync, context-file loading, session snapshots, and skill mounts cannot import unapproved host files into project-controlled execution. Limit trusted host context ingestion to the reviewed job snapshot and required skill text.
- [ ] Run `scripts/run_checks.sh unit provider` and `scripts/run_checks.sh integration hermes-routing`; record the pinned Hermes revision and the effective tool/backend configuration. Do not enable any installed profile.

### Task 5: Retain evidence and close lifecycle gaps

**Files:** Create `factory_sandbox/evidence.py`, `tests/test_evidence.py`; modify `runtime.py` and `provider.py`; add lifecycle cases to `tests/integration/test_pilot.py`.

**Interfaces:**

- `EvidenceStore(root: Path).record(identity: AttemptIdentity, event: dict) -> None` atomically records supervisor-generated events in an owned attempt directory.
- `EvidenceStore(root: Path).finish(identity: AttemptIdentity, result: dict) -> Path` writes the final attempt summary, including image identities, workspace identity, policy revision, start/end times, exit reason, output identity, and cleanup outcome. Never serialize raw host environments or credentials.
- A supervisor cleanup operation validates ownership, stops execution, collects validated output, records the outcome, and removes resources in that order. Failed collection preserves the workspace for diagnosis rather than destroying the only output.

- [ ] Add failing tests for cancellation with a background process, worker death, proxy death, initialization failure after namespace creation, interrupted result collection, repeated session-end hooks, and a restarted supervisor observing an old attempt.
- [ ] Implement atomic evidence updates and ownership-checked cleanup. Preserve primary execution errors and separately report cleanup errors. Repeated cleanup resumes only incomplete owned steps; it must not double-import output or adopt another attempt's resources.
- [ ] Attach a bounded human-readable outcome/evidence reference through the existing Kanban mechanism in the isolated pilot. Keep model comments separate from supervisor evidence; no worker-provided command is executed by the host. Do not add new production database columns or UI surfaces for the pilot.
- [ ] Run `scripts/run_checks.sh unit evidence runtime provider` and `scripts/run_checks.sh integration pilot-lifecycle`. Require all project processes to be gone and output/evidence to remain readable after cancellation. Verify fresh restart creates a new container from retained files and the frozen policy; no uncontrolled command replay.

### Task 6: Complete a disposable Factory pilot and document rollout

**Files:** Create `scripts/run_pilot.py`, `tests/integration/test_pilot.py`, `docs/pilot-results.md`; update the example profile/policy and compatibility guide.

**Interfaces:** `scripts/run_pilot.py --hermes-source PATH --output PATH` prepares an isolated home, private board, fixture project, and test-only worker profile; executes a small file-change task through the actual Kanban worker path; exports validated output/evidence; and tears down only its owned runtime resources.

- [ ] Build a fixture task with a fixed acceptance criterion: change a small source file and produce the existing Factory manifest. Keep credentials synthetic except the host-only model credential strictly needed for an actual agent run; a deterministic handler/routing test alone is not recorded as an agent pilot.
- [ ] Run a real implementation and independent read/verification handoff against the same approved result snapshot using isolated profiles. Ensure the existing task/attempt/manifest identifiers match returned artifacts and that no change reaches a live source checkout.
- [ ] Run the full plugin unit suite and the scoped integration suite once. Use the Hermes canonical runner for relevant upstream compatibility checks: `scripts/run_tests.sh tests/tools/test_docker_backend_real.py tests/tools/test_docker_session_isolation.py tests/tools/test_file_tools_container_config.py`. Set its documented image fixture and isolated state; report any check that cannot run.
- [ ] Record allowed and blocked network cases, filesystem denials, cross-job isolation, model/command placement, cancellation, output retention, and resource cleanup in `docs/pilot-results.md`. Include exact version/image/policy identities and expected versus observed outcomes. Do not claim full Factory or Unity isolation.
- [ ] Document the later activation procedure with a reviewable profile diff and explicit rollback: stop pilot admission, stop/collect/remove owned resources, retain evidence, and leave sandbox-required tasks blocked. Do not change default profiles, schedulers, publisher scripts, or installed code as part of the pilot.
- [ ] Review the complete diff and all evidence against the approved spec. Keep implementation and activation separate; request any filesystem escalation only when a concrete installation/configuration write is ready and actually required. Ask separately before any commit or push.

## Self-review and execution handoff

Spec coverage: policy/workspace isolation → Task 2; enforced egress → Tasks 1/3; tool routing and scope → Task 4; cancellation/recovery/evidence → Task 5; real Factory handoff and rollout → Task 6. Unity and publishing are explicitly bounded in every stage. Each Review Focus item has corresponding behavioral checks above.

The compatibility gate is intentional: the existing proxy documentation does not prove network confinement, and the Docker constructor adds mounts/environment automatically. Task 1 must prove those exact seams before implementation relies on them. A failed gate requires a reviewed adjustment, not reduced acceptance criteria.

Recommended execution: native implementation in this session, task by task, because the provider, namespace lifecycle, and workspace contracts are tightly coupled. No agent delegation has been authorized. Review this plan and select the execution method before product code is written, as required by the writing-plans workflow.
