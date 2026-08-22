# Dispatch recipes

Prefer `scripts/run.py --plan plan.json`. This file is the fallback if you must type CLI by hand.

Repo root: `git rev-parse --show-toplevel` or cwd. Pass the prompt as an argv item, not via `$(cat ...)`.

Worker preamble is in `SKILL.md`. Append the item spec after it.

Orca is optional. If `IN_ORCA` is not true, skip the Orca section and use CLI.

## CLI (default)

**impl** (`codex` present). If `HOST=codex`, do the item here instead.

```bash
codex exec -C "<repo>" -s workspace-write --approve-for-me -c 'model_reasoning_effort="medium"' "$(cat "$PROMPT_FILE")"
```

Mechanical items: `model_reasoning_effort="low"`. User-requested xhigh only.

**hard** (`claude` present, session under skip threshold). Not for impl.

```bash
claude -p --output-format text --disable-slash-commands --tools "" --model sonnet "$(cat "$PROMPT_FILE")"
```

Architecture plans: `--model opus`.

**write / review** (`grok` present). If `HOST=grok`, do the item here instead.

```bash
grok -p --permission-mode acceptEdits "$(cat "$PROMPT_FILE")"
```

**research** — use `LANE_RESEARCH_BIN` from probe.

Gemini:

```bash
gemini -p "$(cat "$PROMPT_FILE")"
```

Hermes (probe prints `LANE_RESEARCH_HOME` when set):

```bash
HERMES_HOME="<LANE_RESEARCH_HOME>" hermes chat -q "$(cat "$PROMPT_FILE")" -Q --in "<repo>"
```

Cursor Agent / OpenCode / Copilot CLI: only if probe listed that BIN and the user asked for that provider. Same rule — prompt file, no yolo flags.

If the BIN is `missing`, mark `skip(no binary)` and tell the user which install they need.

## Orca (only when `IN_ORCA=true` and `ORCA=ready`)

Supervise:

```bash
orca orchestration run-create --objective "<goal>" --json
orca orchestration task-create --spec "<item spec>" --json
orca orchestration worker-start --task <id> --worktree current --agent grok|codex|claude [--model <id> --effort <level>] --json
orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 900000 --json
```

Handoff:

```bash
orca worktree create --name <name> --agent grok|codex|claude --prompt "$(cat "$PROMPT_FILE")" --setup run --json
```

Do not use `coordinator-start`. Do not pass `--agent` values that probe did not list as a BIN.
