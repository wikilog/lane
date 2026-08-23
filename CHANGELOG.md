# Changelog

## 0.10.0

- Policy board: `STATUS.md` shows limits, a why column, and Refused (skip/fallback).
- `audit` item when impl is paired with other work. Never `via=here`. Grok weekly skip does not block execute.
- Review reads `diff.patch` (git diff + untracked). Unparsed verdict cannot pass. One rework, then blocked. No score loop.

## 0.9.1

- Always-on: `always-on.md` linked into `~/.grok/rules` and `~/.claude/rules`. Claude/Codex/Hermes AGENTS blocks so ordinary chat orchestrates without `/lane`.

## 0.9.0

- Ordinary chat dispatches without `/lane` when work is off-host or mixed. Short on-lane edits stay here.
- A dead worker is retried once on the same provider, then Qwen → MiniMax. Impl still never spills to Claude.

## 0.8.1

- Impl/mechanical fallback order is Qwen 3.8-Max then MiniMax-M3. Still never spill impl to Claude.

## 0.8.0

- Grok·Codex runtime models are unpinned (CLI catalog default), matching Claude `sonnet`/`opus` aliases.
- 15-day refresh (`scripts/refresh_models.py`, Hermes cron `1,16 09:00`) updates snapshot + `model-matrix.md`.
- Fallback workers when a primary is exhausted or missing: MiniMax-M3 for impl, Qwen 3.8-Max for hard/write. Still never spill impl to Claude.
- `never_assign` is `maxi` only. MiniMax host remains coordinator-only.

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
