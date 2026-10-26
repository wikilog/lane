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
    "Report files changed and the result. Do not paste secrets. Do not git commit.\n\n"
)
REVIEW_TAIL = (
    "Read ONLY {patch}. Ignore worker summaries and logs. "
    'Reply with JSON only: {{"verdict":"pass"|"fail"|"blocked","notes":"..."}}. '
    "Do not edit files. Do not commit."
)
POLICY_LINE = "never_spill_impl_to_claude · review ≠ impl ≠ host · skip not spill"
REVIEW_JSON_SHAPE = (
    '{"verdict":"pass"|"fail"|"blocked","notes":"why",'
    '"rewrite":"unified diff that fixes it when fail, else empty"}'
)


def review_prompt_text(spec: str, diff_path: Path) -> str:
    return (
        WORKER_PREAMBLE
        + (spec or "")
        + "\n\n"
        + f"Read ONLY this file: {diff_path}\n"
        + "It holds the whole change set (`git diff HEAD` plus untracked files). "
        + "Do not open worker logs, stdout, or last_message; the diff is the only "
        + "ground truth.\n"
        + f"Reply with JSON only: {REVIEW_JSON_SHAPE}\n"
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
    # "current" resolves against the *invoking process's* cwd (not a fixed
    # session concept) — execute_item passes item.get("repo") or the run's
    # --cwd as that subprocess cwd, so a per-item "repo" field is enough to
    # target a different repo per item within one multi-repo /lane batch.
    worker_start = [
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
    ]
    return [
        ["orca", "orchestration", "run-create", "--objective", goal or "lane", "--json"],
        ["orca", "orchestration", "task-create", "--spec", item.get("spec") or "", "--json"],
        worker_start,
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
    readonly = bool(item.get("readonly") or item.get("kind") in {"audit", "review"})
    if provider == "codex":
        cmd = ["codex", "exec"]
        if approve:
            cmd.append("--approve-for-me")
        model = item.get("model")
        if model:
            cmd.extend(["-m", str(model)])
        cmd.extend(
            [
                "-C",
                str(repo),
                "-s",
                "read-only" if readonly else "workspace-write",
            ]
        )
        # "default"는 lane 설정의 "모델 기본값"이라 codex 에 넘기면 Invalid value 로 실패한다(write→codex 대체 때)
        if effort != "default":
            cmd.extend(["-c", f'model_reasoning_effort="{effort}"'])
        cmd.append("-")
        return cmd, prompt_text, None
    if provider == "claude":
        model = item.get("model") or (
            "opus" if item.get("kind") == "hard" and effort == "high" else "sonnet"
        )
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
            "plan" if readonly else "acceptEdits",
            "--cwd",
            str(repo),
        ], None, None
    if provider == "gemini":
        return ["gemini", "-p"], prompt_text, None
    if provider in {"hermes", "minimax", "qwen"} or item.get("home"):
        cmd = [
            "hermes",
            "chat",
            "-q",
            pointer(prompt_path),
            "-Q",
            "--in",
            str(repo),
        ]
        model = item.get("model")
        if model:
            cmd.extend(["-m", str(model)])
        return cmd, None, None
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


def parse_verdict(text: str) -> dict | None:
    if not text or not str(text).strip():
        return None
    decoder = json.JSONDecoder()
    raw = str(text).strip()
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and obj.get("verdict"):
            return obj
    except json.JSONDecodeError:
        pass
    last = None
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("verdict"):
            last = obj
    return last


def write_diff(repo: Path, dest: Path) -> None:
    parts: list[str] = []
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        parts.append(diff.stdout or "")
        others = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        for rel in (others.stdout or "").splitlines():
            rel = rel.strip()
            if not rel:
                continue
            show = subprocess.run(
                ["git", "diff", "--no-index", "--", "/dev/null", rel],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=30,
            )
            parts.append(show.stdout or "")
    except (OSError, subprocess.SubprocessError):
        pass
    dest.write_text("".join(parts), encoding="utf-8")


def _pct(value) -> str:
    return f"{value}%" if value is not None else "-"


def _limit_line(limits: dict, name: str) -> str:
    block = limits.get(name) if isinstance(limits.get(name), dict) else {}
    return f"- {name}: session {_pct(block.get('session_pct'))} · weekly {_pct(block.get('weekly_pct'))}"


def status_md(plan: dict, results: list[dict], run_dir: Path, repo: Path) -> str:
    limits = plan.get("limits") or {}
    lines = [
        f"# lane run `{run_dir.name}`",
        "",
        f"- goal: {plan.get('goal')}",
        f"- host: {plan.get('host')} · in_orca: {plan.get('in_orca')} · supervise: {plan.get('supervise')}",
        f"- cwd: {repo}",
        f"- limits_known: {plan.get('limits_known')}",
        f"- policy: {POLICY_LINE}",
        "",
        "## Limits",
        "",
        _limit_line(limits, "claude"),
        _limit_line(limits, "codex"),
        _limit_line(limits, "grok"),
        "",
        "| kind | provider | via | status | needs | why |",
        "|------|----------|-----|--------|-------|-----|",
    ]
    for rec in results:
        needs = ",".join(rec.get("needs") or [])
        why = " ".join(str(rec.get("reason") or "").split())
        lines.append(
            f"| {rec.get('kind')} | {rec.get('provider')} | {rec.get('via')} | {rec.get('status')} | {needs} | {why} |"
        )
    refused = [
        rec
        for rec in results
        if rec.get("via") == "skip" or rec.get("fallback") or rec.get("status") in {"skipped", "blocked"}
    ]
    if refused:
        lines += ["", "## Refused", ""]
        for rec in refused:
            lines.append(f"- {rec.get('kind')} `{rec.get('provider')}` {rec.get('via')}: {rec.get('reason') or rec.get('status')}")
    for rec in results:
        lines += ["", f"## {rec.get('kind')}", ""]
        if rec.get("reason"):
            lines.append(rec["reason"])
        if rec.get("verdict"):
            lines.append(f"verdict: {rec['verdict']}")
        if rec.get("spec"):
            lines.append("```")
            lines.append(rec["spec"])
            lines.append("```")
        if rec.get("log"):
            lines.append(f"log: `{rec['log']}`")
        if rec.get("attempts"):
            lines.append("attempts: " + ", ".join(
                f"{a.get('provider')}={a.get('status')}" for a in rec["attempts"]
            ))
    lines.append("")
    return "\n".join(lines)


def diff_patch_commands() -> list[list[str]]:
    """Commands that build the change set: tracked diff plus untracked list."""
    return [
        ["git", "diff", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]


def write_diff(repo: Path, out_path: Path) -> Path:
    """Write `git diff HEAD` plus untracked-file diffs from repo to out_path.

    An empty change set still produces the file.
    """
    diff_cmd, untracked_cmd = diff_patch_commands()
    parts: list[str] = []
    cp = subprocess.run(
        diff_cmd, cwd=str(repo), check=False, capture_output=True, text=True, timeout=60
    )
    if cp.stdout:
        parts.append(cp.stdout)
    cp = subprocess.run(
        untracked_cmd, cwd=str(repo), check=False, capture_output=True, text=True, timeout=60
    )
    for name in (cp.stdout or "").splitlines():
        name = name.strip()
        if name.startswith('"') and name.endswith('"') and len(name) > 1:
            name = name[1:-1]
        if not name or name.startswith("/"):
            continue
        target = repo / name
        if not target.is_file():
            continue
        sub = subprocess.run(
            ["git", "diff", "--no-index", "--", os.devnull, str(target)],
            cwd=str(repo),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if sub.stdout:
            parts.append(sub.stdout)
    out_path.write_text("".join(parts), encoding="utf-8")
    return out_path


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


def bind_worker(
    item: dict,
    rec: dict,
    repo: Path,
    prompt_path: Path,
    prompt_text: str,
    approve: bool,
    supervise: bool,
    goal: str,
) -> bool:
    argv, stdin_text, steps = argv_for(
        item, repo, prompt_path, prompt_text, approve, supervise, goal
    )
    rec["argv"] = argv
    rec["provider"] = item.get("provider")
    rec["via"] = item.get("via")
    if stdin_text is not None:
        rec["stdin"] = True
        rec["stdin_text"] = stdin_text
    else:
        rec.pop("stdin", None)
        rec.pop("stdin_text", None)
    if steps:
        rec["steps"] = steps
    else:
        rec.pop("steps", None)
    return bool(argv)


def run_attempts(
    item: dict,
    rec: dict,
    *,
    repo: Path,
    prompt_path: Path,
    prompt_text: str,
    approve: bool,
    supervise: bool,
    goal: str,
    timeout: int,
    env: dict,
    run_bound: list[bool],
    log_path: Path,
) -> tuple[int, str, str, str, list[dict]]:
    attempts: list[dict] = []
    current = dict(item)
    chain = list(item.get("retry_chain") or [])
    same_left = 1
    chain_i = 0
    code = 1
    stdout = ""
    stderr = ""
    status = "no-argv"
    chunks: list[str] = []
    # An item may name its own target repo (multi-repo /lane batch); "current"
    # in orca_supervise_steps resolves against whatever cwd we run orca with,
    # so route that item to its own repo instead of the run's global --cwd.
    item_repo = item.get("repo")
    effective_repo = Path(item_repo).expanduser().resolve() if item_repo else repo
    while True:
        if not bind_worker(current, rec, effective_repo, prompt_path, prompt_text, approve, supervise, goal):
            status = "no-argv"
            attempts.append(
                {"provider": current.get("provider"), "via": current.get("via"), "status": status}
            )
            break
        try:
            env_try = dict(env)
            if current.get("home"):
                env_try["HERMES_HOME"] = current["home"]
            else:
                env_try.pop("HERMES_HOME", None)
            code, stdout, stderr = execute_item(rec, effective_repo, timeout, env_try, run_bound)
            status = "ok" if code == 0 else f"exit {code}"
        except subprocess.TimeoutExpired:
            code, stdout, stderr, status = 1, "", "", "timeout"
        except OSError as exc:
            code, stdout, stderr, status = 1, "", str(exc), f"oserror {exc}"
        attempts.append(
            {
                "provider": current.get("provider"),
                "via": current.get("via"),
                "status": status,
            }
        )
        chunks.append(f"# attempt {len(attempts)} {current.get('provider')} {status}\n{stdout}\n{stderr}\n")
        if code == 0:
            item["provider"] = current.get("provider")
            item["via"] = current.get("via")
            item["home"] = current.get("home")
            item["model"] = current.get("model")
            item["reason"] = current.get("reason")
            if current.get("fallback"):
                item["fallback"] = True
            break
        if same_left:
            same_left -= 1
            continue
        if chain_i < len(chain):
            nxt = chain[chain_i]
            chain_i += 1
            prev = current.get("provider")
            # model·home 은 앞 공급자 것이라 다음 공급자에 넘기지 않는다(chain 항목에 있으면 그것을 쓴다)
            current = {k: v for k, v in item.items() if k not in ("model", "home")}
            current.update(nxt)
            current["via"] = nxt.get("via") or "cli"
            current["fallback"] = True
            current["reason"] = f"retry {nxt.get('provider')} after {prev} {status}"
            continue
        break
    log_path.write_text("\n".join(chunks), encoding="utf-8")
    return code, stdout, stderr, status, attempts


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
    patch = run_dir / "diff.patch"
    reworked = False

    def prompt_for(item: dict) -> str:
        spec = item.get("spec") or ""
        if item.get("kind") == "review":
            spec = spec + "\n" + REVIEW_TAIL.format(patch=patch)
        return WORKER_PREAMBLE + spec

    def write_audit(rec: dict) -> None:
        if rec.get("kind") != "audit":
            return
        if rec.get("status") == "skipped" or rec.get("via") == "skip":
            (run_dir / "AUDIT.md").write_text(
                f"skipped: {rec.get('reason') or 'skip'}\n", encoding="utf-8"
            )
            return
        text = rec.get("stdout") or ""
        if text:
            (run_dir / "AUDIT.md").write_text(text, encoding="utf-8")

    def apply_review(rec: dict) -> None:
        parsed = parse_verdict(rec.get("stdout") or "")
        if not parsed:
            rec["verdict"] = "unparsed"
            if rec.get("status") == "ok":
                rec["status"] = "unparsed"
            return
        rec["verdict"] = str(parsed.get("verdict") or "").lower()
        rec["review_notes"] = parsed.get("notes")
        if rec["verdict"] != "pass" and rec.get("status") == "ok":
            rec["status"] = rec["verdict"] if rec["verdict"] in {"fail", "blocked"} else "fail"

    def run_item(item: dict) -> dict:
        rec = {
            "kind": item["kind"],
            "via": item.get("via"),
            "provider": item.get("provider"),
            "reason": item.get("reason"),
            "spec": item.get("spec"),
            "needs": item.get("needs") or [],
            "retry_chain": item.get("retry_chain") or [],
            "fallback": bool(item.get("fallback")),
        }
        blocked_by = [n for n in rec["needs"] if n in failed]
        if blocked_by:
            rec["status"] = "blocked"
            rec["reason"] = f"blocked by failed {','.join(blocked_by)}"
            failed.add(item["kind"])
            return rec
        if item.get("via") == "skip":
            rec["status"] = "skipped"
            return rec
        if item.get("via") == "here":
            rec["status"] = "coordinator"
            return rec
        prompt_text = prompt_for(item)
        prompt_path = prompts / f"{item['kind']}.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        rec["prompt"] = str(prompt_path)
        rec["spec"] = prompt_text
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
            return rec
        if not args.execute:
            rec["status"] = "dry-run"
            rec.pop("stdin_text", None)
            return rec
        log_path = logs / f"{item['kind']}.log"
        rec["log"] = str(log_path)
        env = os.environ.copy()
        secret_env = Path.home() / ".local/bin/secret-env"
        if item.get("provider") == "grok" and not env.get("GBRAIN_TOKEN_GROK") and secret_env.exists():
            # grok 설정은 gbrain 토큰을 이 env 에서 읽는다(apply-mcp.sh 가 평문 대신 bearer_token_env_var 로 둔다).
            # secret-env 가 없는 머신(맥북)이나 조회 실패면 토큰 없이 띄운다: gbrain 만 빠지고 grok 작업은 돈다
            try:
                tok = subprocess.run([str(secret_env), "-v", "GBRAIN_TOKEN_GROK"],
                                     capture_output=True, text=True, timeout=20).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                tok = ""
            if tok:
                env["GBRAIN_TOKEN_GROK"] = tok
        code, stdout, stderr, status, attempts = run_attempts(
            item,
            rec,
            repo=repo,
            prompt_path=prompt_path,
            prompt_text=prompt_text,
            approve=approve,
            supervise=supervise,
            goal=goal,
            timeout=args.timeout,
            env=env,
            run_bound=run_bound,
            log_path=log_path,
        )
        rec["attempts"] = attempts
        rec.pop("stdin_text", None)
        rec["status"] = status
        rec["stdout"] = (stdout or "")[-4000:]
        rec["stderr"] = (stderr or "")[-2000:]
        rec["provider"] = item.get("provider")
        rec["via"] = item.get("via")
        rec["reason"] = item.get("reason") or rec.get("reason")
        rec["fallback"] = bool(item.get("fallback"))
        if code != 0:
            failed.add(item["kind"])
        return rec

    for item in ready_order(plan.get("items") or []):
        rec = run_item(item)
        if rec.get("kind") == "audit":
            write_audit(rec)
        if (
            rec.get("kind") in {"impl", "mechanical"}
            and args.execute
            and rec.get("status") == "ok"
        ):
            write_diff(Path(item["repo"]).expanduser().resolve() if item.get("repo") else repo, patch)
        if rec.get("kind") == "review" and args.execute and rec.get("status") not in {
            "skipped",
            "blocked",
            "coordinator",
            "dry-run",
            "no-argv",
        }:
            apply_review(rec)
            impl = next((r for r in results if r.get("kind") == "impl"), None)
            if rec.get("verdict") != "pass" and impl and impl.get("status") == "ok" and not reworked:
                reworked = True
                notes = rec.get("review_notes") or rec.get("verdict")
                impl_src = next(i for i in plan["items"] if i["kind"] == "impl")
                impl_src = dict(impl_src)
                impl_src["spec"] = (impl_src.get("spec") or "") + f"\nRework after review {rec.get('verdict')}: {notes}"
                failed.discard("impl")
                impl2 = run_item(impl_src)
                impl.update(impl2)
                if impl2.get("status") == "ok":
                    write_diff(Path(impl_src["repo"]).expanduser().resolve() if impl_src.get("repo") else repo, patch)
                    failed.discard("review")
                    rec = run_item(item)
                    apply_review(rec)
                if rec.get("verdict") != "pass":
                    rec["status"] = "blocked"
                    failed.add("review")
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
