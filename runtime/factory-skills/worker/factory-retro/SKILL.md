---
name: factory-retro
description: Analyze retained Factory project and task evidence and propose measurable improvements without changing the Factory.
---

# Factory retrospective

Read the captured project history and retained plans, task outputs, verification reports, reviews and repair evidence. Distinguish observed facts from hypotheses. Cite task/run IDs and retained artifact paths for each conclusion.

Write `RETRO.md` in the assigned scratch workspace:

1. Outcome and evidence coverage, including anything unavailable.
2. Repeated failures and their root causes; distinguish product defects, planning gaps, environment gaps and Factory defects.
3. Prioritized improvement proposals for planning, prompts, role selection, tooling, verification, reviews, repair routing, or scheduling. Each proposal includes evidence, expected benefit, tradeoffs and a concrete validation check.
4. What worked and should be preserved.
5. Decisions that require the user's approval.

Use the managed worker handoff, retain `RETRO.md`, and use the inherited project AC IDs in `ac_ids`. Finish DONE only after the report exists. Do not rewrite the project plan. If evidence is missing, say so; do not fabricate usage, costs, timings or tool results.

Never modify Factory code, skills, profiles, configuration, templates, model defaults or the project. Never publish, commit, push or create work. Recommendations require a separate authorized implementation task. A failed project remains failed; retro cannot waive its findings.
