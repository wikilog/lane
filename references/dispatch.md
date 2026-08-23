# Dispatch recipes

Prefer `scripts/run.py --plan plan.json --cwd <project>`. This file is the fallback if you must type CLI by hand.

Workers read the spec from `prompts/<kind>.txt` (or stdin). Do not interpolate the prompt with command substitution.

Repo: `--cwd` or `git rev-parse --show-toplevel`. Never use the lane skill package as the project unless that is the repo you are changing.

Worker preamble is in `SKILL.md`. It is already prepended in the prompt file `run.py` writes.

Orca is optional. If `IN_ORCA` is not true, skip the Orca section and use CLI.

## CLI (default)

Prompt file: `$PROMPT_FILE`. Stdin: `codex` (`-`) and `claude`/`gemini` (`-p` with no prompt arg).

**impl** (`codex` present). If `HOST=codex`, do the item here instead. Do not pass `-m` unless the plan set a cheap mechanical tier.

```bash
codex exec -C "<repo>" -s workspace-write -c 'model_reasoning_effort="medium"' -
```

Pipe the prompt file to stdin. Mechanical items: `model_reasoning_effort="low"` and optional `-m` from the snapshot cheap tier. User-requested xhigh only. `--approve-for-me` only when plan `approve_for_me` is true.

**hard** (`claude` present, session under skip threshold). Not for impl. Default tools stay on so the worker can edit. Family alias, not a dated slug.

```bash
claude -p --output-format text --disable-slash-commands --model sonnet
```

Architecture plans: `--model opus`. Prompt on stdin.

**write** (`grok` present). If `HOST=grok`, do the item here instead. Do not pass `-m`; the CLI catalog default tracks.

```bash
grok --prompt-file "$PROMPT_FILE" --permission-mode acceptEdits --cwd "<repo>"
```

**audit / review** (`grok` present). Audit is never `here`. Review reads `diff.patch` only.

```bash
grok --prompt-file "$PROMPT_FILE" --permission-mode plan --cwd "<repo>"
```

**fallback** when the primary is exhausted or the binary is missing (not when limits are unknown), and when a worker dies. Same provider once, then Qwen → MiniMax. `HERMES_HOME` from the plan item. Never spill impl to Claude.

- impl/mechanical/hard/write/review → `~/.hermes-qwen` (qwen3.8-max), then `~/.hermes-minimax` (MiniMax-M3)

**research** — use `LANE_RESEARCH_BIN` from probe.

Gemini (prompt on stdin):

```bash
gemini -p
```

Hermes (probe prints `LANE_RESEARCH_HOME` when set):

```bash
HERMES_HOME="<LANE_RESEARCH_HOME>" hermes chat -q "Read and follow $PROMPT_FILE. Do only that item." -Q --in "<repo>"
```

Cursor Agent / OpenCode / Copilot CLI: only if probe listed that BIN and the user asked for that provider. Same rule — prompt file or stdin, no yolo flags.

If the BIN is `missing`, mark `skip(no binary)` and tell the user which install they need.

## Orca (only when `IN_ORCA=true` and `ORCA=ready`)

Supervise (default, `supervise: true`):

```bash
orca orchestration run-create --objective "<goal>" --json
orca orchestration task-create --spec "<item spec>" --json
orca orchestration worker-start --task <id> --worktree current --agent grok|codex|claude --json
orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 900000 --json
```

Handoff (`supervise: false`):

```bash
orca worktree create --name <name> --agent grok|codex|claude --prompt "Read and follow $PROMPT_FILE. Do only that item." --setup run --json
```

Do not use `coordinator-start`. Do not pass `--agent` values that probe did not list as a BIN. `--effort` on `worker-start` requires `--model`; omit both unless the plan names a model id.
