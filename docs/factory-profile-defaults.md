# Factory profile defaults (reference snapshot, 2026-11-15)

Live profile configs (`~/.hermes/profiles/<name>/config.yaml`) are untracked and are the source of truth.
This file records the cost-reduced settings so they can be restored after a reinstall.

Rules learned the hard way:
- `factory-orchestrator` runs the PLAN/scope stage with the `factory-worker` skill, so its `skills.external_dirs`
  must include BOTH `~/.hermes/factory-skills/orchestrator` and `~/.hermes/factory-skills/worker`.
  Without it the stage dies with `Unknown skill(s): factory-worker`.
- Do not use the `copilot` provider (not licensed on this account); the catalog still lists copilot models.
- After editing plugin code under `~/.hermes/plugins/factory-models` run `hermes gateway restart` while no stage is
  running; the gateway keeps the old module loaded.

- Every profile has its OWN copy of the plugin at `~/.hermes/profiles/<name>/plugins/factory-models`, and a worker's
  completion-time reconcile imports that copy. After changing `~/.hermes/plugins/factory-models`, sync all of them:
  `for d in ~/.hermes/profiles/*/plugins/factory-models; do rsync -a --delete --exclude __pycache__ ~/.hermes/plugins/factory-models/ $d/; done`
  Stale copies silently ran old validation for several attempts on 2026-11-15.

| profile | provider | model | effort | skill dirs |
|---|---|---|---|---|
| architect | anthropic | claude-sonnet-5-5 | medium | worker |
| art-director | anthropic | claude-sonnet-5-5 | medium | worker |
| art-reviewer | anthropic | claude-sonnet-5-5 | low | worker |
| artist | openai-codex | gpt-6-luna | medium | worker |
| audio-director | anthropic | claude-sonnet-5-5 | medium | worker |
| claude-reviewer | anthropic | claude-sonnet-5-5 | low | worker |
| codex-reviewer | openai-codex | gpt-6-sol | high | worker |
| developer | anthropic | claude-sonnet-5-5 | medium | worker |
| factory-orchestrator | openai-codex | gpt-6-astra | medium | orchestrator, worker |
| factory-retro | anthropic | claude-sonnet-5-5 | low | worker |
| fixer | anthropic | claude-sonnet-5-5 | medium | worker |
| pr-writer | anthropic | claude-sonnet-5-5 | low | publisher |
| security-reviewer | anthropic | claude-sonnet-5-5 | low | worker |
| sound-designer | openai-codex | gpt-6-luna | medium | worker |
| trailz | llamacpp | Qwen3-8B-Q4_K_M | low | - |
| ui-reviewer | anthropic | claude-sonnet-5-5 | low | worker |
| ux-reviewer | anthropic | claude-sonnet-5-5 | low | worker |
| verifier | anthropic | claude-sonnet-5-5 | low | worker |

## Automatic recovery
`factory-resume-rate-limit` (cron, every 2 minutes, no LLM; `runtime/factory-dashboard/scripts/factory_resume_rate_limit.py`,
deployed to `~/.hermes/scripts/`) resumes a workflow root that stopped only because a worker hit a provider rate limit
(429 / usage limit). It uses the controller's own resume, waits 10 minutes between tries and gives up after 24.
It never touches human gates (plan approval) or real failures (`human_review`).
