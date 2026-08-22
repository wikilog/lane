---
name: lane
description: >
  Split a mixed implement/docs/review request across Codex, Grok, and Claude
  and dispatch it. Use when the user runs /lane or says 레인, 나눠서, 조율,
  오케스트레이션, 모델별로 실행. Skip for a short single-lane edit in the
  current app.
license: MIT
compatibility: Claude Code, Codex, Grok, MiniMax (coordinator only), Cursor, Gemini CLI, OpenCode, Hermes, Orca. Python 3.9+ for scripts.
metadata:
  author: marcus
  version: "0.7.0"
  sku: lane
---

# /lane

Coordinator only. MiniMax may coordinate; it is never a worker. This session does only `here` items. Everything else is `run.py --execute`.

## Path (do this, in order)

```bash
DIR="${LANE_SKILL_DIR:-$HOME/.agents/skills/lane}"
python3 "$DIR/scripts/probe.py"
python3 "$DIR/scripts/plan.py" --prompt-file "$PROMPT_FILE" > "$HOME/.cache/lane/last-plan.json"
# optional: edit last-plan.json once (kinds / via only)
python3 "$DIR/scripts/run.py" --plan "$HOME/.cache/lane/last-plan.json" --cwd "$PWD"
```

`run.py` writes `~/.cache/lane/runs/<timestamp>/`. Do not pass `--run-dir current`.

1. Print `STATUS.md` from the JSON `run_dir` (the board).
2. `/lane plan` or `/route-model` → stop.
3. `/lane` / 나눠서 / 실행 → same `run.py` with `--execute --cwd "$PWD"`. Then do every `coordinator` (`here`) item yourself. Do not implement `cli` / `orca` items in this session.
4. Stop if a needed item failed (`blocked` in STATUS). One verify pass after workers, different vendor from impl. Retry impl at most once, and only if the user asked.

Do not load dispatch.md unless `run.py` is missing.

## Plan JSON

`kind` → lane: write/review → Grok, impl/mechanical → Codex, hard → Claude, research → cheap research CLI.

`via`: `here` this session · `cli` provider CLI · `orca` only if `IN_ORCA=true` · `skip` do not substitute another paid CLI.

`supervise: true` (default in an Orca terminal) → `worker-start` + `worker_done`. `supervise: false` → `worktree create` handoff.

Gates: missing bin; Codex weekly 100% (no Claude spill); Claude session ≥ skip_at; Grok weekly ≥ skip_at for write CLI; **that provider's** limits unknown → skip impl/hard CLI; never_assign; review vendor ≠ impl **and** ≠ host.

`needs` is the graph. `STATUS.md` is what the user sees.

## Do not

- Spend this session on another lane
- Spill exhausted Codex impl onto Claude
- Re-invoke `/lane` from a worker
- Dual-review the same diff on two coding CLIs
- Pass `--yolo` or `--dangerously-bypass-*`
- Use `--approve-for-me` unless plan `approve_for_me` is true
