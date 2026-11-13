# Project workflows, version 2

Implement the user-approved project/task hierarchy without changing captured v1 runs.

1. Track the installed dashboard/plugin source in `runtime/factory-dashboard` so changes are reviewable and reproducible.
2. Add an opt-in execution version captured in template revisions. A v2 project runs scope classification, relevant art/audio directors, then the code architect. The architect retains a validated small-task dependency graph. Scope and director/architecture evidence is inherited by every task.
3. Execute dependency-ready tasks serially in the shared project directory. Each owns acceptance criteria and a selected writer. Require a successful independent verifier before materializing code/security reviews and relevant UI/UX/art/audio reviews. Preserve ownership/run/manifest and mutation guards, restart safety, and bounded repairs.
4. Route repair findings to code fixer, artist, or sound-designer; mixed repairs run serially. Repeat verification and the full selected panel on the repaired manifest. Missing render/listening evidence cannot pass specialist review.
5. Run a final integration cycle over the assembled project and all project acceptance criteria. Then run `factory-retro` to retain evidence-backed improvement proposals. Retro cannot change the Factory or publish.
6. Add regression tests first: ordering, dependency validation, restart/idempotence, verifier failure, stale evidence, repair routing, unavailable perception tools, final integration, retro, and v1 compatibility.
7. Provide preview/apply installation with baseline checks, backups, new template revisions, role/skill/profile registration, and bundled plugin updates. Do not launch model work during validation or rewrite existing snapshots.
8. Update the README, workflow guide, and SVG. Verify tests, installed disposable-board behavior, and diagram rendering. No commit/push without a fresh explicit request.

Sound matching requires real listening evidence (a capable tool or retained human evaluation). Without that capability the workflow must stop honestly instead of equating loudness/spectrum measurements with perceptual approval. Art matching requires evidence from the running/rendered integration against the director's retained criteria, not only isolated asset thumbnails.
