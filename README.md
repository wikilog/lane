# lane

[Agent Skill](https://agentskills.io/specification) that splits a mixed request by model specialty and **dispatches** it. Version **0.7.0**. See [CHANGELOG](CHANGELOG.md).

- Writing / second review → Grok-class CLI
- Implementation / tests / terminal → Codex
- Architecture / stuck debug → Claude
- Long research → a cheap research CLI (Gemini or Hermes)

The current chat does not spend its quota on another model's job. Each run writes a board at `~/.cache/lane/runs/<timestamp>/STATUS.md`.

Works in Claude Code, Codex, Grok, MiniMax (coordinator only), Cursor, Gemini CLI, Hermes, and OpenCode. Orca is optional and used only inside an Orca terminal.

`/lane plan` prints the assignment. `/lane` (or “나눠서”, “실행”) runs it. The coordinator session does `here` items only; other lanes go through `run.py --execute`.

## Install

Python 3.9+ on PATH. Provider CLIs are optional; missing binaries become `skip`.

```bash
git clone https://github.com/wikilog/lane.git
cd lane
./scripts/install-links.sh
python3 scripts/test_plan.py
```

`install-links.sh` points `~/.agents/skills/lane` (and Claude / Codex / Grok skill roots) at this clone, and also `~/skills/library/lane` if you keep a skills hub. Keep the directory name `lane`. Hermes already scans `~/.agents/skills`.

Override the skill path with `LANE_SKILL_DIR` when the clone lives somewhere else.

## Use

```text
/lane 로그인 폼 고치고 카피 다듬고 리스크 리뷰해 줘
/lane plan <task>
```

```bash
python3 scripts/probe.py
python3 scripts/plan.py --prompt-file ./prompt.txt > ~/.cache/lane/last-plan.json
# optional: edit last-plan.json once (kinds / via only)
python3 scripts/run.py --plan ~/.cache/lane/last-plan.json --cwd "$PWD"
# unique ~/.cache/lane/runs/<timestamp>/STATUS.md is the board
python3 scripts/run.py --plan ~/.cache/lane/last-plan.json --cwd "$PWD" --execute
```

`--cwd` is the project workers should touch. If you run the scripts from this skill repo, passing `--cwd` is required. `--run-dir current` is refused so boards are not overwritten. Dry-run is the default; add `--execute` to start workers. After `--execute`, do every `coordinator` (`here`) item in the current session.

`--prompt` still works. `--plan -` reads plan JSON from stdin.

## What you see

```text
~/.cache/lane/runs/<timestamp>/
  STATUS.md      board (table + per-lane spec)
  plan.json
  results.json
  prompts/       text sent to each worker
  logs/          CLI output after --execute
```

`via: here` stays in the current session. `cli` sends the spec on stdin (`codex` / `claude` / `gemini`) or `--prompt-file` (`grok`). Inside an Orca terminal, `supervise` (default) uses `worker-start` + `worker_done`; `supervise: false` is a `worktree create` handoff. `skip` does not spill onto another paid CLI.

## Configure

Defaults: `references/default-config.json`. Override without editing the skill:

1. `~/.config/lane/config.json` — this machine
2. `<repo>/.lane.json` — this project (wins)

See `references/config.example.json`. Useful keys: `supervise_default`, `claude_session_skip_at`, `grok_weekly_skip_at`, `never_spill_impl_to_claude`, `approve_for_me`, `lanes`, `providers`. Do not commit machine paths or secrets.

Limits come from Orca `account list` when the app is up, then Claude dashboard `check-usage` fills gaps (Claude session/weekly, Codex when that script reports them). Probe prints `LIMITS_SOURCE=orca`, `cli`, or `orca+cli`.

## Token rules

- Small on-lane work stays in the current session
- Workers get a short spec file, not the chat, and not a prompt stuffed into argv
- Same diff is not sent to two coding CLIs
- Exhausted Codex weekly does not spill implementation onto Claude
- Review uses a different vendor from implementation **and** from the host
- Limits unknown for that provider → do not dispatch impl/hard
- `run.py` is dry-run unless `--execute`
- The coordinator does not implement `cli` / `orca` items

## License

MIT. See [LICENSE](LICENSE).
