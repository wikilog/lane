---
name: lane
description: >
  Split implement/docs/review/research work across Codex, Grok, Claude, and
  fallbacks, and dispatch it. Use for ordinary chat that never says /lane
  whenever the request is coding, docs, review, architecture, or research
  that should not all run on this host. Also use for /lane, 레인, 나눠서,
  조율, 오케스트레이션, 모델별로 실행. Skip a short question with no file
  work, and skip a short single-lane edit this host already owns. Workers
  must not re-invoke.
license: MIT
compatibility: Claude Code, Codex, Grok, MiniMax (coordinator only), Cursor, Gemini CLI, OpenCode, Hermes, Orca. Python 3.9+ for scripts.
metadata:
  author: marcus
  version: "0.10.0"
  sku: lane
---

# /lane

Coordinator only. MiniMax host sessions coordinate; they are not `via=here` workers. MiniMax-M3 and Qwen 3.8-Max are fallback workers when a primary lane is exhausted or missing, or when a worker dies. This session does only `here` items. Everything else is `run.py --execute`.

Do not wait for `/lane`. If the user asked for work that `plan.py` would split or send off-host, run the path below and execute. Stay in this session only when every item is `via=here` (short on-lane edit) or the request is a question with no file work.

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
2. `/lane plan` or `/route-model` → stop after the plan. Do not execute.
3. Ordinary work, `/lane`, 나눠서, 실행 → `run.py --execute --cwd "$PWD"`. Then do every `coordinator` (`here`) item yourself. Do not implement `cli` / `orca` items in this session.
4. `run.py` retries a dead worker once on the same provider, then walks `retry_chain` (Qwen then MiniMax). It does not spill impl to Claude. Stop if STATUS still shows `blocked` after those retries. One verify pass after workers, different vendor from impl.

Do not load dispatch.md unless `run.py` is missing.

## Plan JSON

`kind` → lane: write/review → Grok, impl/mechanical → Codex, hard → Claude, research → cheap research CLI.

Runtime models are unpinned family defaults (Claude `sonnet`/`opus`, Grok/Codex CLI catalog default). Mechanical may pass the cheap Codex tier from the 15-day snapshot. `scripts/refresh_models.py` rewrites `~/.config/lane/model-snapshot.json` and `route-model/references/model-matrix.md`.

Config merge, later wins: skill package defaults → SkillOps `profiles/lanes.yaml` (`SKILLOPS_LANES` or `~/.config/skillops/lanes.yaml`) → `~/.config/lane/config.json` → project `.lane.json`. Manual files always override the synced profile.

`via`: `here` this session · `cli` provider CLI · `orca` only if `IN_ORCA=true` · `skip` after fallbacks also fail.

`supervise: true` (default in an Orca terminal) → `worker-start` + `worker_done`. `supervise: false` → `worktree create` handoff.

Gates: missing bin; Codex weekly 100% (no Claude spill → Qwen then MiniMax); Claude session ≥ skip_at → Qwen then MiniMax; Grok weekly ≥ skip_at for write CLI → Qwen then MiniMax; **that provider's** limits unknown → skip impl/hard CLI (no fallback); never_assign (`maxi` only); review vendor ≠ impl **and** ≠ host.

When the plan has `impl` plus another item, add `audit` (write CLI, never `here`). Grok weekly skip on audit does not block execute. Review reads `diff.patch`, not the worker summary. Unparsed review cannot pass. One impl rework after fail, then `blocked`. No score loop.

`needs` is the graph. `STATUS.md` is the policy board (why, refused, limits).

## Do not

- Spend this session on another lane
- Spill exhausted Codex impl onto Claude
- Re-invoke `/lane` from a worker
- Dual-review the same diff on two coding CLIs
- Pass `--yolo` or `--dangerously-bypass-*`
- Use `--approve-for-me` unless plan `approve_for_me` is true
