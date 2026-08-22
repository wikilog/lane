# lane

[Agent Skill](https://agentskills.io/specification) that splits a mixed request by model specialty and **dispatches** it.

- Writing / second review → Grok-class CLI
- Implementation / tests / terminal → Codex
- Architecture / stuck debug → Claude
- Long research → a cheap research CLI (Gemini or Hermes)

The current chat does not spend its quota on another model's job. Each run writes a board at `~/.cache/lane/runs/<id>/STATUS.md`.

Works in Claude Code, Codex, Grok, MiniMax (coordinator only), Cursor, Gemini CLI, Hermes, and OpenCode. Orca is optional and used only inside an Orca terminal.

`/lane plan` prints the assignment. `/lane` (or “나눠서”, “실행”) runs it.

## Install

Python 3.9+ on PATH. Provider CLIs are optional; missing binaries become `skip`.

```bash
git clone https://github.com/wikilog/lane.git
cd lane
mkdir -p ~/.agents/skills ~/.claude/skills ~/.codex/skills ~/.grok/skills
ln -sfn "$(pwd)" ~/.agents/skills/lane
ln -sfn "$(pwd)" ~/.claude/skills/lane
ln -sfn "$(pwd)" ~/.codex/skills/lane
ln -sfn "$(pwd)" ~/.grok/skills/lane
```

Keep the directory name `lane`. Hermes already scans `~/.agents/skills`.

```bash
python3 scripts/test_plan.py
```

## Use

```text
/lane 로그인 폼 고치고 카피 다듬고 리스크 리뷰해 줘
/lane plan <task>
```

```bash
python3 scripts/probe.py
python3 scripts/plan.py --prompt "로그인 폼 고치고 카피 다듬어 줘" > /tmp/lane-plan.json
python3 scripts/run.py --plan /tmp/lane-plan.json --run-dir ~/.cache/lane/runs/demo
# STATUS.md is the board. Add --execute only when you want workers started.
```

## What you see

```text
~/.cache/lane/runs/<id>/
  STATUS.md      board (table + per-lane spec)
  plan.json
  results.json
  prompts/       text sent to each worker
  logs/          CLI output after --execute
```

`via: here` stays in the current session. `cli` / `orca` shows up as extra CLI or an Orca tab named `lane-<kind>`. `skip` does not spill onto another paid CLI.

## Configure

Defaults: `references/default-config.json`. Override without editing the skill:

1. `~/.config/lane/config.json` — this machine
2. `<repo>/.lane.json` — this project (wins)

See `references/config.example.json`. Do not commit machine paths or secrets.

## Token rules

- Small on-lane work stays in the current session
- Workers get a short spec, not the chat
- Same diff is not sent to two coding CLIs
- Exhausted Codex weekly does not spill implementation onto Claude
- Review uses a different vendor from implementation **and** from the host
- Limits unknown for that provider → do not dispatch impl/hard
- `run.py` is dry-run unless `--execute`

## License

MIT. See [LICENSE](LICENSE).
