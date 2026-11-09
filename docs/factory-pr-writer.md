# Factory PR writer

The draft PR that `~/.hermes/scripts/factory_publish.py` opens for a delivered job now leads with a body written by the `pr-writer` profile (skill `factory-pr`, adapted from mattpocock/skills `engineering/pr` and `engineering/retro`):

```text
publish(root)                                   factory_publish.py
  check manifest, writer gates, commit, push
  write_pr_body
    write_dossier -> kanban/workspaces/pr-<root>-*/dossier/
      root.md  PLAN.md  diff.patch  diffstat.txt  stages.json
    hermes -p pr-writer chat --oneshot -s factory-pr     (file tools only, write-guarded)
      -> PR.md: Summary (pseudocode) / Evidence / Merge Danger / Factory Retro
    reject unless Summary, Evidence, Merge Danger, Door, Blast Radius are present
  body = PR.md + collapsed "Factory result and plan"   (fallback: the old plan body)
  gh pr create --draft
```

- Files: `~/.hermes/factory-skills/publisher/factory-pr/` (SKILL.md, CREDITS.md), `~/.hermes/profiles/pr-writer/` (SOUL.md, config.yaml), `factory_publish.py`, `factory_lib.py` defaults, `scripts/tests/test_publish.py`.
- Config (`~/.hermes/state/factory/config.json`): `pr_writer_profile` (default `pr-writer`; `""` disables), `pr_writer_timeout` (default 420 s).
- A writer failure, timeout or malformed body never blocks the PR. The publisher prints `pr-writer not used for <root> (<why>)` and opens the PR with the plan body, as before.
- The pr-writer is not in any dispatch roster. Only the publisher calls it.
- Rollback: restore `factory_publish.py.bak-pre-prwriter` and `tests/sandbox.py.bak-pre-prwriter`, or set `pr_writer_profile` to `""`.
