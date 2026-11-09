# Factory sandbox: first milestone

Status: proposed for review; implementation has not started.

## Intent and agreed constraints

Run one Factory coding task with isolated command execution and file operations. Outbound network access must be limited to approved destinations and enforced independently of worker cooperation. Preserve the existing staged Factory workflow and return changes and execution evidence to it.

The user selected allowlisted network access and accepted starting with sandboxed worker commands and file operations. The Hermes coordinator and model calls remain trusted host processes in this milestone. This is a defined execution boundary, not isolation of the entire agent process.

## Evidence from the installed factory

- Source installation: `/Users/example/.hermes/hermes-agent`.
- Factory configuration and scripts: `/Users/example/.hermes/factory-skills`, `/Users/example/.hermes/profiles`, and `/Users/example/.hermes/scripts`.
- `hermes_cli/kanban_db_dispatch.py::_default_spawn` launches worker processes on the host, sets their profile scope, and anchors them to the assigned workspace.
- Worker profiles inspected have no explicit terminal backend. `hermes_cli/config_defaults.py` defaults the backend to `local`.
- `tools/environments/docker.py` already implements containers and resource restrictions. Reuse that backend where its existing contracts permit.
- `tools/environments/docker_egress.py` integrates iron-proxy. The installed egress guide documents a direct socket bypass, so proxy environment variables and CA settings alone do not meet the agreed requirement.
- Factory intake creates linked Git worktrees. Their shared Git metadata must not accidentally expose the original checkout inside a sandbox.
- Factory scripts include host-side Unity execution and publishing. Those are separate execution and authority boundaries.

These are static source/configuration observations. Effective runtime behavior and Docker availability have not yet been exercised.

## Alternatives and selection

1. Sandbox terminal and file tools while keeping the coordinator on the host. This reuses the existing backend and minimizes changes to Kanban and model authentication. It requires auditing every enabled worker tool to identify host execution paths.
2. Isolate the complete worker process. This covers a wider boundary but needs a constrained service interface for Kanban, model credentials, artifacts, and lifecycle control.

Select option 1 for the first milestone. Its success must not be described as complete worker or complete Factory isolation.

## Components and ownership

### Trusted run supervisor

The host supervisor owns sandbox creation, immutable policy selection, workspace preparation, resource limits, teardown, and evidence collection. Workers cannot change the selected policy, access the Docker API, or request an unrestricted replacement runtime. A sandbox startup failure blocks the stage; it never falls back to local execution.

Keep this integration at the existing runtime/backend boundary. Follow the Hermes repository's extension policy and existing configuration conventions; do not introduce a new model tool or duplicate its dispatcher.

### Workspace

Prepare a dedicated job snapshot with no host secrets and no writable connection to the main checkout or shared Git metadata. Mount or copy only that job's workspace into its container. Do not expose the host home directory, Hermes state directories, SSH agent, credential stores, Docker socket, or other task workspaces.

Preserve approved changes across sequential stages using host-owned job storage. Use separate stage container identities; do not share a persistent container by role. The supervisor owns import/export and rejects symlinks or paths that escape the job root. Preserve the existing manifest and review identity contracts.

Start with a disposable fixture repository. General worktree/snapshot compatibility is a rollout prerequisite, not an assumption.

### Execution and file tools

All enabled worker command and file operations must target the assigned container/workspace. Confirm routing for reads, writes, search, background processes, and delegated calls before enabling the profile. Tools that execute on the host or expose unrestricted network operations must be disabled for the pilot or explicitly excluded from the trusted boundary with a documented reason.

Keep model-provider credentials in the trusted host process. Forward no provider keys into the coding container unless a concrete task requires them and an approved credential mechanism exists.

### Enforced outbound access

Use a trusted egress gateway with a destination allowlist. Workers must have no independent route to the internet, host services, LAN, cloud metadata, or other jobs. Proxy variables are convenience settings only.

The intended topology is a dedicated worker network namespace with filtering configured by trusted initialization. Permit only the designated proxy endpoint and required established traffic. Deny other IPv4 and IPv6 traffic, including direct DNS. Drop network administration capabilities from the worker before running project code. The gateway alone has upstream connectivity and resolves approved destinations.

Prefer the existing iron-proxy integration if its addressing and policy configuration support this topology. The implementation plan must establish compatibility from source and a disposable network probe before changing live profiles. If compatibility requires a different gateway deployment, update this design before implementation.

Gateway policy must validate the requested destination and its resolved addresses, prevent access to private/link-local/loopback destinations, and reapply policy to redirects or new connections. Define explicit hostname and port rules. Do not use a global wildcard. Permit only project-required services; bundled model-provider defaults are not automatically the coding task's approved allowlist.

On proxy failure or policy initialization failure, stop or block execution. Do not silently provide direct networking.

### Lifecycle and evidence

Associate the sandbox with the existing task and attempt identifiers. Record the runtime image identity, workspace identity, network policy revision, start/end times, exit reason, and cleanup outcome. Expose actionable failures through the existing stage outcome/comment mechanism.

Cancellation must stop foreground and background project processes. Preserve approved workspace output and evidence before removing execution resources. Recovery may resume retained workspace state in a fresh sandbox with the same policy; it must not adopt an unrelated container.

## Unity and publishing boundary

Host Unity checks execute repository-controlled code, including editor scripts. They remain outside this milestone and must be reported as such. Do not route a failed sandbox command to a host Unity invocation as a fallback.

The initial pilot uses a task that does not require Unity or other host-only tools. Before claiming sandbox coverage for Unity tasks, design a separate constrained execution environment and verify licensing/toolchain requirements.

Existing publishing automation remains outside the worker boundary. The sandbox grants no commit, push, PR, or merge authority. Import/export must not turn arbitrary worker output into host shell commands or executable verification instructions.

## Scenario specifications

#### Scenario: Approved outbound request

- **GIVEN** a task policy permits one hostname and port
- **WHEN** project code requests that destination through the gateway
- **THEN** the request succeeds
- **AND** the run evidence identifies the policy revision.

#### Scenario: Direct connection bypass

- **GIVEN** a worker removes proxy environment variables or opens a raw socket
- **WHEN** it attempts a direct IPv4, IPv6, DNS, host, or LAN connection
- **THEN** network enforcement blocks it.

#### Scenario: Unapproved destination through the proxy

- **GIVEN** a destination is absent from the task allowlist
- **WHEN** a worker requests it through the gateway
- **THEN** the gateway refuses it
- **AND** it does not resolve or redirect the request into a private service.

#### Scenario: Host and sibling workspace access

- **GIVEN** a sandbox has only its assigned job workspace
- **WHEN** project code attempts to read host credentials or another job's files
- **THEN** those resources are unavailable
- **AND** symlinks in exported output cannot escape the assigned workspace.

#### Scenario: Required infrastructure unavailable

- **GIVEN** container creation, network policy initialization, or the gateway fails
- **WHEN** the stage starts or attempts network access
- **THEN** it fails closed with an actionable stage result
- **AND** no local command execution or direct network fallback occurs.

#### Scenario: Cancellation and output preservation

- **GIVEN** a worker has changed job files and started a background process
- **WHEN** the run is cancelled
- **THEN** its project processes stop
- **AND** workspace output and cancellation evidence are preserved before teardown.

## Acceptance and rollout

The milestone is complete only when a disposable coding task passes through the real worker tool routing, returns its expected change and manifest, and demonstrates the allow/deny, filesystem, failure, and cancellation scenarios above. Do not infer isolation from configuration text or a successful proxied HTTP request.

Roll out first to an explicitly selected pilot job/profile. Record the effective configuration and verify that no shared-container setting defeats task separation. Broader role rollout follows only after workspace, tool routing, concurrency, and review handoff compatibility are established.

Rollback disables pilot admission and cleans up its execution resources while retaining workspace/evidence. It must not silently run an admitted sandbox-required task on the local backend.

## Next planning work

Trace backend configuration, file routing, lifecycle cleanup, and proxy policy APIs at the installed revision. Identify the smallest extension/configuration changes and meaningful isolation checks. Prepare the implementation plan after review of this design. No live profile, proxy, Docker network, scheduler, or installed source changes are authorized by this document alone.
