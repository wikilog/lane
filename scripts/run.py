#!/usr/bin/env python3
"""Dispatch a /lane plan. Writes a run folder with STATUS.md. Default is dry-run."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKER_PREAMBLE = (
    "You are a /lane worker. Do not invoke /lane. Do only this item. "
    "Report files changed and the result. Do not paste secrets.\n\n"
)


def repo_root() -> Path:
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if isinstance(raw, bytes):
            raw = raw.decode()
        return Path(str(raw).strip())
    except (OSError, subprocess.SubprocessError):
        return Path.cwd()


def argv_for(item: dict, repo: Path, prompt_text: str, approve: bool) -> list[str] | None:
    if item.get("via") in {None, "skip", "here"}:
        return None
    if item.get("via") == "orca":
        return [
            "orca",
            "worktree",
            "create",
            "--name",
            f"lane-{item['kind']}",
            "--agent",
            item["provider"],
            "--prompt",
            prompt_text,
            "--setup",
            "run",
            "--json",
        ]
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
            prompt_text,
        ]
        if approve:
            cmd[5:5] = ["--approve-for-me"]
        return cmd
    if provider == "claude":
        model = "opus" if item.get("kind") == "hard" and effort == "high" else "sonnet"
        return [
            "claude",
            "-p",
            prompt_text,
            "--output-format",
            "text",
            "--disable-slash-commands",
            "--tools",
            "",
            "--model",
            model,
        ]
    if provider == "grok":
        return ["grok", "-p", "--permission-mode", "acceptEdits", prompt_text]
    if provider == "gemini":
        return ["gemini", "-p", prompt_text]
    if provider == "hermes":
        return ["hermes", "chat", "-q", prompt_text, "-Q", "--in", str(repo)]
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


def status_md(plan: dict, results: list[dict], run_dir: Path) -> str:
    lines = [
        f"# lane run `{run_dir.name}`",
        "",
        f"- goal: {plan.get('goal')}",
        f"- host: {plan.get('host')} · in_orca: {plan.get('in_orca')} · execute: {any(r.get('status') not in {'dry-run', 'skipped', 'coordinator', 'blocked'} and r.get('via') not in {'skip', 'here'} for r in results)}",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Dispatch a /lane plan")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--run-dir")
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text())
    repo = repo_root()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.run_dir) if args.run_dir else Path.home() / ".cache" / "lane" / "runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompts = run_dir / "prompts"
    logs = run_dir / "logs"
    prompts.mkdir(exist_ok=True)
    logs.mkdir(exist_ok=True)

    approve = bool(plan.get("approve_for_me"))
    failed: set[str] = set()
    results: list[dict] = []
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
        argv = argv_for(item, repo, prompt_text, approve)
        rec["argv"] = argv
        if not argv:
            rec["status"] = "no-argv"
            failed.add(item["kind"])
            results.append(rec)
            continue
        if not args.execute:
            rec["status"] = "dry-run"
            results.append(rec)
            continue
        log_path = logs / f"{item['kind']}.log"
        rec["log"] = str(log_path)
        try:
            env = os.environ.copy()
            if item.get("home"):
                env["HERMES_HOME"] = item["home"]
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                env=env,
            )
            log_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
            rec["status"] = "ok" if completed.returncode == 0 else f"exit {completed.returncode}"
            rec["stdout"] = (completed.stdout or "")[-4000:]
            rec["stderr"] = (completed.stderr or "")[-2000:]
            if completed.returncode != 0:
                failed.add(item["kind"])
        except subprocess.TimeoutExpired:
            rec["status"] = "timeout"
            failed.add(item["kind"])
        except OSError as exc:
            rec["status"] = f"oserror {exc}"
            failed.add(item["kind"])
        results.append(rec)

    payload = {
        "goal": plan.get("goal"),
        "execute": args.execute,
        "run_dir": str(run_dir),
        "results": results,
    }
    (run_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "STATUS.md").write_text(status_md(plan, results, run_dir), encoding="utf-8")
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
