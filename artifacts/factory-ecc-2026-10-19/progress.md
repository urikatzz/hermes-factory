# SDD ledger — plan: docs/superpowers/plans/2026-10-19-factory-ecc-adoption.md

Execution: native, user approved design and plan. Build: /private/tmp/factory-ecc-build. Deliver new paths into project after validation.

Pre-flight: task 1 transform feeds task 2 service save; validate with installed WorkflowDefinition. Task 3 taskset/grader identities feed task 4 import. Task 5 consumes migration receipts and reports. Interfaces consistent.

Ruling: use a separate temporary build directory without creating a Git worktree — the project checkout is master with all prior deliveries untracked and Git writes require consent — cost if wrong: source is copied into the project at delivery rather than represented by an isolated branch. No commit/push.

Tasks: 1 guidance; 2 migration; 3 fixtures/graders; 4 reporting; 5 activation/delivery.

Task 1: complete — 3 focused tests pass. Task 2: complete — 5 real-service tests pass; live preview created, no live mutations. JSON sequence normalization fixed after reproducing tuple/list receipt mismatch.
Task 3: fixture preparation complete — 4 tests pass; grader sandbox checks pending.

Task 3: complete — 4 fixture tests and 6 sandbox baseline/reference checks pass; immutable runtime image recorded in grader-checks.json. Temporary sandbox source archived (37 files) with hashes.
Task 4: complete — importer/report/CLI checks pass; full suite 27/27. Synthetic example prepared. A genuine verifier failure now counts as failed rather than incomplete (reproduced RED then fixed GREEN).
Ruling: retain taskset/variant/provenance metadata in a list subclass so empty imports still report configured variants — preserves the planned list interface — cost if wrong: one small container type to maintain.
Ruling: functional graders are not tamper-resistant and require operator-reviewed provenance — no containment/promotion claim — cost if wrong: imported grades must be independently reviewed before being trusted.
Final fresh-context review dispatched under executing-plans/requesting-code-review skill. No implementation delegation.

Task 5 in progress: new package/scripts/fixtures/tests copied into the project; docs/factory-ecc.md written. Pre-review project suite 27/27, syntax and CLI help checks pass. Read-only installed-state checksums captured. Three templates preview revision 1→2, no active state modified.
Ruling: validate installed instruction routing by building real stage cards from WorkflowCapture.preview without dispatching paid workers — the change is entirely captured text and launch machinery is unchanged — cost if wrong: actual provider adherence still requires real trials.

Final review: 4 Important and 1 Minor; all reproduced in review-fixes-red.log. One fix pass completed; 33/33 tests green. Fixed contradictory attempts, failure denominators, cross-template rollback, evidence output collisions and malformed reviewer profile. No deferred findings.
Ruling: malformed-profile finding is required schema validation, so included in the fix pass — contract promises malformed input rejection — cost if wrong: one extra guard and regression test.
Generated compileall caches in example candidate directories invalidated their source manifests as intended; removed only newly generated caches and regenerated synthetic reports. Future checks disable bytecode output.

Task 5: complete — installed Feature/Bug fix/Chore revision 2; receipts in /Users/example/.hermes/backups/factory-ecc-20261019-guidance. Nine installed stage cards verified. Unrelated settings and all historical revisions preserved by checksum. Fresh preview empty; fresh no-op apply complete with zero saves. Final tests 33/33; six sandbox grader checks, zero model calls. No commits/pushes. No deferred review findings. All source/evidence retained as durable record.
