# Changelog

## 0.7.0

- Unique run dirs at `~/.cache/lane/runs/<timestamp>/`. `--run-dir current` is refused.
- Coordinator session does `here` items only. Other lanes run through `run.py --execute`.
- `--cwd` is required when the process cwd is the skill package.
- Worker prompts go through a file or stdin, not argv command substitution.
- Orca default is supervise (`worker-start`). `supervise: false` is a `worktree create` handoff.
- Limits overlay: Orca `account list`, then Claude dashboard `check-usage` when a provider is still empty.
- `scripts/install-links.sh` points host skill roots (and `~/skills/library/lane`) at this clone.
- Classifier: docs-like `함수` / `배포 가이드` / `설계 문서` stay on write. English `and` splits clauses.

## 0.6.0

- First public MIT release: probe → plan JSON → `run.py` board, fail-closed limits, review vendor split.
