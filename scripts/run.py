#!/usr/bin/env python3
"""Dispatch a /lane plan. Unique run folder + STATUS.md. Default is dry-run."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
WORKER_PREAMBLE = (
    "You are a /lane worker. Do not invoke /lane. Do only this item. "
    "Report files changed and the result. Do not paste secrets.\n\n"
)


def git_root(start: Path) -> Path | None:
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if isinstance(raw, bytes):
            raw = raw.decode()
        return Path(str(raw).strip())
    except (OSError, subprocess.SubprocessError):
        return None


def resolve_repo(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    start = Path.cwd().resolve()
    git = git_root(start) or start
    if git.resolve() == SKILL_DIR.resolve():
        raise SystemExit("lane: pass --cwd <project>; refusing the skill package as the repo")
    return git.resolve()


def load_plan(path: str) -> dict:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text()
    return json.loads(raw)


def pointer(prompt_path: Path) -> str:
    return f"Read and follow {prompt_path}. Do only that item."


def orca_supervise_steps(item: dict, goal: str) -> list[list[str]]:
    return [
        ["orca", "orchestration", "run-create", "--objective", goal or "lane", "--json"],
        ["orca", "orchestration", "task-create", "--spec", item.get("spec") or "", "--json"],
        [
            "orca",
            "orchestration",
            "worker-start",
            "--task",
            "<task_id>",
            "--worktree",
            "current",
            "--agent",
            item["provider"],
            "--json",
        ],
        [
            "orca",
            "orchestration",
            "check",
            "--wait",
            "--types",
            "worker_done,escalation,question",
            "--timeout-ms",
            "900000",
            "--json",
        ],
    ]


def argv_for(
    item: dict,
    repo: Path,
    prompt_path: Path,
    prompt_text: str,
    approve: bool,
    supervise: bool,
    goal: str,
) -> tuple[list[str] | None, str | None, list[list[str]] | None]:
    via = item.get("via")
    if via in {None, "skip", "here"}:
        return None, None, None
    if via == "orca":
        if supervise:
            steps = orca_supervise_steps(item, goal)
            return steps[2], None, steps
        argv = [
            "orca",
            "worktree",
            "create",
            "--name",
            f"lane-{item['kind']}",
            "--agent",
            item["provider"],
            "--prompt",
            pointer(prompt_path),
            "--setup",
            "run",
            "--json",
        ]
        return argv, None, None
    provider = item.get("provider")
    effort = item.get("effort") or "medium"
    if provider == "codex":
        cmd = [
            "codex",
            "exec",
            "-C",
            str(repo),
            "-s",
            "workspace-write",
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-",
        ]
        if approve:
            cmd[5:5] = ["--approve-for-me"]
        return cmd, prompt_text, None
    if provider == "claude":
        model = "opus" if item.get("kind") == "hard" and effort == "high" else "sonnet"
        return [
            "claude",
            "-p",
            "--output-format",
            "text",
            "--disable-slash-commands",
            "--model",
            model,
        ], prompt_text, None
    if provider == "grok":
        return [
            "grok",
            "--prompt-file",
            str(prompt_path),
            "--permission-mode",
            "acceptEdits",
            "--cwd",
            str(repo),
        ], None, None
    if provider == "gemini":
        return ["gemini", "-p"], prompt_text, None
    if provider == "hermes":
        return [
            "hermes",
            "chat",
            "-q",
            pointer(prompt_path),
            "-Q",
            "--in",
            str(repo),
        ], None, None
    return None, None, None


def pick_id(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(result, dict):
        return None
    for key in ("taskId", "task_id", "id"):
        if result.get(key):
            return str(result[key])
    task = result.get("task")
    if isinstance(task, dict):
        for key in ("id", "taskId", "task_id"):
            if task.get(key):
                return str(task[key])
    return None


def ready_order(items: list[dict]) -> list[dict]:
    remaining = list(items)
    done: set[str] = set()
    ordered: list[dict] = []
    while remaining:
        progress = False
        nxt = []
        for item in remaining:
            needs = [n for n in (item.get("needs") or []) if n not in done]
            if needs:
                nxt.append(item)
                continue
            ordered.append(item)
            done.add(item["kind"])
            progress = True
        if not progress:
            ordered.extend(nxt)
            break
        remaining = nxt
    return ordered


def status_md(plan: dict, results: list[dict], run_dir: Path, repo: Path) -> str:
    lines = [
        f"# lane run `{run_dir.name}`",
        "",
        f"- goal: {plan.get('goal')}",
        f"- host: {plan.get('host')} · in_orca: {plan.get('in_orca')} · supervise: {plan.get('supervise')}",
        f"- cwd: {repo}",
        f"- limits_known: {plan.get('limits_known')}",
        "",
        "| kind | provider | via | status | needs |",
        "|------|----------|-----|--------|-------|",
    ]
    for rec in results:
        needs = ",".join(rec.get("needs") or [])
        lines.append(
            f"| {rec.get('kind')} | {rec.get('provider')} | {rec.get('via')} | {rec.get('status')} | {needs} |"
        )
    for rec in results:
        lines += ["", f"## {rec.get('kind')}", ""]
        if rec.get("reason"):
            lines.append(rec["reason"])
        if rec.get("spec"):
            lines.append("```")
            lines.append(rec["spec"])
            lines.append("```")
        if rec.get("log"):
            lines.append(f"log: `{rec['log']}`")
    lines.append("")
    return "\n".join(lines)


def run_cmd(
    argv: list[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        cwd=str(cwd),
        input=stdin_text,
    )


def execute_item(
    rec: dict,
    repo: Path,
    timeout: int,
    env: dict,
    run_bound: list[bool],
) -> tuple[int, str, str]:
    steps = rec.get("steps")
    if steps:
        task_id = None
        stdout_acc = []
        stderr_acc = []
        for step in steps:
            argv = list(step)
            if argv[:3] == ["orca", "orchestration", "run-create"] and run_bound[0]:
                continue
            if "<task_id>" in argv:
                if not task_id:
                    return 1, "", "no task id"
                argv = [task_id if a == "<task_id>" else a for a in argv]
            completed = run_cmd(argv, cwd=repo, timeout=timeout, env=env)
            stdout_acc.append(completed.stdout or "")
            stderr_acc.append(completed.stderr or "")
            if completed.returncode != 0:
                return completed.returncode, "\n".join(stdout_acc), "\n".join(stderr_acc)
            try:
                data = json.loads(completed.stdout or "{}")
            except json.JSONDecodeError:
                data = {}
            if argv[:3] == ["orca", "orchestration", "run-create"]:
                run_bound[0] = True
            if argv[:3] == ["orca", "orchestration", "task-create"]:
                task_id = pick_id(data)
                if not task_id:
                    return 1, "\n".join(stdout_acc), "no task id from task-create"
        return 0, "\n".join(stdout_acc), "\n".join(stderr_acc)
    argv = rec.get("argv")
    if not argv:
        return 1, "", "no-argv"
    completed = run_cmd(
        argv,
        cwd=repo,
        timeout=timeout,
        env=env,
        stdin_text=rec.get("stdin_text"),
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch a /lane plan")
    parser.add_argument("--plan", required=True, help="plan JSON path, or - for stdin")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--run-dir")
    parser.add_argument("--cwd", help="project directory workers should use")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    repo = resolve_repo(args.cwd)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.run_dir) if args.run_dir else Path.home() / ".cache" / "lane" / "runs" / stamp
    if run_dir.name == "current":
        raise SystemExit("lane: --run-dir current overwrites the board; use a unique folder")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompts = run_dir / "prompts"
    logs = run_dir / "logs"
    prompts.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)

    approve = bool(plan.get("approve_for_me"))
    supervise = bool(plan.get("supervise"))
    goal = plan.get("goal") or "lane"
    failed: set[str] = set()
    results: list[dict] = []
    run_bound = [False]
    for item in ready_order(plan.get("items") or []):
        rec = {
            "kind": item["kind"],
            "via": item.get("via"),
            "provider": item.get("provider"),
            "reason": item.get("reason"),
            "spec": item.get("spec"),
            "needs": item.get("needs") or [],
        }
        blocked_by = [n for n in rec["needs"] if n in failed]
        if blocked_by:
            rec["status"] = "blocked"
            rec["reason"] = f"blocked by failed {','.join(blocked_by)}"
            results.append(rec)
            failed.add(item["kind"])
            continue
        if item.get("via") == "skip":
            rec["status"] = "skipped"
            results.append(rec)
            continue
        if item.get("via") == "here":
            rec["status"] = "coordinator"
            results.append(rec)
            continue
        prompt_text = WORKER_PREAMBLE + (item.get("spec") or "")
        prompt_path = prompts / f"{item['kind']}.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        rec["prompt"] = str(prompt_path)
        argv, stdin_text, steps = argv_for(
            item, repo, prompt_path, prompt_text, approve, supervise, goal
        )
        rec["argv"] = argv
        if stdin_text is not None:
            rec["stdin"] = True
            rec["stdin_text"] = stdin_text
        if steps:
            rec["steps"] = steps
        if not argv:
            rec["status"] = "no-argv"
            failed.add(item["kind"])
            results.append(rec)
            continue
        if not args.execute:
            rec["status"] = "dry-run"
            rec.pop("stdin_text", None)
            results.append(rec)
            continue
        log_path = logs / f"{item['kind']}.log"
        rec["log"] = str(log_path)
        try:
            env = os.environ.copy()
            if item.get("home"):
                env["HERMES_HOME"] = item["home"]
            code, stdout, stderr = execute_item(rec, repo, args.timeout, env, run_bound)
            rec.pop("stdin_text", None)
            log_path.write_text(stdout + "\n" + stderr, encoding="utf-8")
            rec["status"] = "ok" if code == 0 else f"exit {code}"
            rec["stdout"] = stdout[-4000:]
            rec["stderr"] = stderr[-2000:]
            if code != 0:
                failed.add(item["kind"])
        except subprocess.TimeoutExpired:
            rec.pop("stdin_text", None)
            rec["status"] = "timeout"
            failed.add(item["kind"])
        except OSError as exc:
            rec.pop("stdin_text", None)
            rec["status"] = f"oserror {exc}"
            failed.add(item["kind"])
        results.append(rec)

    payload = {
        "goal": plan.get("goal"),
        "execute": args.execute,
        "cwd": str(repo),
        "run_dir": str(run_dir),
        "results": results,
    }
    (run_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "STATUS.md").write_text(status_md(plan, results, run_dir, repo), encoding="utf-8")
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
