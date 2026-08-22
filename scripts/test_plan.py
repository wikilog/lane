#!/usr/bin/env python3
"""Fixture tests for /lane plan gates. No live workers."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import plan  # noqa: E402


def probe(
    host: str,
    *,
    orca: str = "ready",
    in_orca: bool = False,
    claude_session: int | None = 10,
    codex_weekly: int | None = 20,
    grok_weekly: int | None = 5,
    bins: dict | None = None,
) -> dict:
    bins = bins or {
        "orca": "/usr/bin/orca",
        "codex": "/usr/bin/codex",
        "claude": "/usr/bin/claude",
        "grok": "/usr/bin/grok",
        "gemini": "missing",
        "hermes": "/usr/bin/hermes",
        "cursor": "missing",
        "opencode": "missing",
    }
    return {
        "HOST": host,
        "IN_ORCA": in_orca,
        "ORCA": orca,
        "CLAUDE_SESSION_SKIP_AT": 90,
        "GROK_WEEKLY_SKIP_AT": 90,
        "NEVER_SPILL_IMPL_TO_CLAUDE": True,
        "NEVER_ASSIGN": ["minimax", "maxi"],
        "BINS": bins,
        "LANES": {
            "write": {"provider": "grok", "bin": bins["grok"], "effort": "default"},
            "impl": {"provider": "codex", "bin": bins["codex"], "effort": "medium"},
            "hard": {"provider": "claude", "bin": bins["claude"], "effort": "high"},
            "research": {"provider": "hermes", "bin": bins["hermes"], "home": "", "effort": "default"},
        },
        "LANE_MECHANICAL_EFFORT": "low",
        "SUPERVISE": True,
        "LIMITS": {
            "claude": {"session_pct": claude_session, "weekly_pct": 15},
            "codex": {"weekly_pct": codex_weekly, "reset_credits": 1},
            "grok": {"weekly_pct": grok_weekly},
        },
    }


def kinds(p: dict) -> list[str]:
    return [i["kind"] for i in p["items"]]


def item(p: dict, kind: str) -> dict:
    return next(i for i in p["items"] if i["kind"] == kind)


class PlanTests(unittest.TestCase):
    MIXED = "로그인 폼 고치고, 카피 다듬고, 리스크 리뷰해 줘."

    def test_mixed_from_grok_splits_three_ways(self):
        p = plan.build_plan(self.MIXED, probe("grok"), "run")
        self.assertEqual(set(kinds(p)), {"impl", "write", "review"})
        self.assertEqual(item(p, "write")["via"], "here")
        self.assertNotEqual(item(p, "review")["provider"], "grok")
        self.assertNotEqual(item(p, "review")["via"], "here")
        self.assertEqual(item(p, "impl")["via"], "cli")
        self.assertEqual(p["tokens"], "split")

    def test_orca_terminal_may_use_worker_start(self):
        p = plan.build_plan(self.MIXED, probe("grok", in_orca=True), "run")
        self.assertEqual(item(p, "impl")["via"], "orca")

    def test_outside_orca_uses_cli_even_if_app_is_ready(self):
        p = plan.build_plan(self.MIXED, probe("claude", orca="ready", in_orca=False), "run")
        self.assertEqual(item(p, "write")["via"], "cli")
        self.assertEqual(item(p, "impl")["via"], "cli")

    def test_codex_weekly_full_does_not_spill_impl_to_claude(self):
        p = plan.build_plan(self.MIXED, probe("grok", codex_weekly=100), "run")
        impl = item(p, "impl")
        self.assertEqual(impl["via"], "skip")
        self.assertIn("do not spill", impl["reason"])
        self.assertNotEqual(impl["provider"], "claude")

    def test_claude_session_full_skips_hard(self):
        p = plan.build_plan("아키텍처 설계 검토해 줘", probe("grok", claude_session=100), "run")
        self.assertEqual(item(p, "hard")["via"], "skip")

    def test_minimax_host_can_coordinate_but_is_never_a_worker(self):
        p = plan.build_plan(self.MIXED, probe("minimax", orca="down"), "run")
        self.assertTrue(all(i["provider"] != "minimax" for i in p["items"]))
        self.assertTrue(all(i["via"] != "here" for i in p["items"]))
        self.assertEqual(item(p, "impl")["via"], "cli")
        self.assertEqual(item(p, "write")["via"], "cli")

    def test_on_lane_small_write_stays_here(self):
        p = plan.build_plan("README 초안만 다듬어 줘", probe("grok"), "run")
        self.assertEqual(kinds(p), ["write"])
        self.assertEqual(p["items"][0]["via"], "here")
        self.assertEqual(p["tokens"], "kept on-lane")

    def test_codex_host_keeps_impl_here(self):
        p = plan.build_plan("버그 고쳐 줘", probe("codex"), "run")
        self.assertEqual(item(p, "impl")["via"], "here")

    def test_claude_host_keeps_hard_here_when_session_ok(self):
        p = plan.build_plan("아키텍처 설계 도와줘", probe("claude", claude_session=20), "run")
        self.assertEqual(item(p, "hard")["via"], "here")

    def test_missing_bin_skips(self):
        bins = {
            "orca": "missing",
            "codex": "missing",
            "claude": "/usr/bin/claude",
            "grok": "/usr/bin/grok",
            "gemini": "missing",
            "hermes": "missing",
            "cursor": "missing",
            "opencode": "missing",
        }
        p = plan.build_plan("버그 고쳐 줘", probe("grok", orca="missing", bins=bins), "run")
        self.assertEqual(item(p, "impl")["via"], "skip")

    def test_hangul_does_not_count_as_write(self):
        p = plan.build_plan("한글만 확인해 줘", probe("codex"), "run")
        self.assertNotIn("write", kinds(p))
        self.assertEqual(kinds(p), ["impl"])

    def test_docker_is_not_docs(self):
        p = plan.build_plan("docker compose 올려", probe("codex"), "run")
        self.assertNotIn("write", kinds(p))

    def test_item_spec_isolates_clauses(self):
        p = plan.build_plan(self.MIXED, probe("grok"), "run")
        impl_spec = item(p, "impl")["spec"]
        self.assertIn("로그인", impl_spec)
        self.assertNotIn("카피", impl_spec)
        self.assertNotIn("리뷰", impl_spec)

    def test_item_spec_isolates_without_comma(self):
        p = plan.build_plan("로그인 폼을 고치고 카피를 다듬어 줘", probe("grok"), "run")
        self.assertNotIn("카피", item(p, "impl")["spec"])
        self.assertIn("카피", item(p, "write")["spec"])

    def test_fail_closed_without_codex_weekly_even_if_grok_known(self):
        data = probe("grok")
        data["LIMITS"] = {"grok": {"weekly_pct": 10}}
        p = plan.build_plan(self.MIXED, data, "run")
        self.assertEqual(item(p, "impl")["via"], "skip")
        self.assertIn("codex", item(p, "impl")["reason"])

    def test_fail_closed_without_limits(self):
        data = probe("grok")
        data["LIMITS"] = {}
        p = plan.build_plan(self.MIXED, data, "run")
        self.assertEqual(item(p, "impl")["via"], "skip")
        self.assertIn("fail closed", item(p, "impl")["reason"])
        self.assertEqual(item(p, "write")["via"], "here")

    def test_review_splits_off_impl_vendor(self):
        data = probe("codex")
        data["LANES"]["write"]["provider"] = "codex"
        data["LANES"]["write"]["bin"] = data["BINS"]["codex"]
        p = plan.build_plan("버그 고치고 리뷰해 줘", data, "run")
        self.assertEqual(item(p, "impl")["provider"], "codex")
        self.assertNotEqual(item(p, "review")["provider"], "codex")

    def test_review_waits_on_impl(self):
        p = plan.build_plan(self.MIXED, probe("grok", codex_weekly=20), "run")
        self.assertEqual(item(p, "review")["needs"], ["impl"])

    def test_run_dry_run_prints_cli_argv(self):
        data = probe("claude", in_orca=False)
        p = plan.build_plan("카피 다듬어 줘", data, "run")
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / "plan.json"
            run_dir = Path(td) / "run"
            proj = Path(td) / "proj"
            proj.mkdir()
            plan_path.write_text(json.dumps(p), encoding="utf-8")
            import subprocess
            out = subprocess.check_output(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "--plan",
                    str(plan_path),
                    "--run-dir",
                    str(run_dir),
                    "--cwd",
                    str(proj),
                ],
                text=True,
            )
            parsed = json.loads(out)
            self.assertFalse(parsed["execute"])
            write = next(r for r in parsed["results"] if r["kind"] == "write")
            self.assertEqual(write["argv"][0], "grok")
            self.assertIn("--prompt-file", write["argv"])
            self.assertFalse(any("Do ONLY" in a for a in write["argv"]))
            self.assertTrue(Path(parsed["run_dir"], "STATUS.md").is_file())

    def test_execute_failure_blocks_review(self):
        import io
        import subprocess
        from unittest.mock import patch
        import run as lane_run
        data = probe("grok", claude_session=10, codex_weekly=20)
        p = plan.build_plan(self.MIXED, data, "run")
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / "plan.json"
            run_dir = Path(td) / "run"
            proj = Path(td) / "proj"
            proj.mkdir()
            plan_path.write_text(json.dumps(p), encoding="utf-8")
            def fake_run(cmd, **kwargs):
                if cmd and cmd[0] == "git":
                    return subprocess.CompletedProcess(cmd, 0, stdout="/tmp\n", stderr="")
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fail")
            buf = io.StringIO()
            argv = ["run.py", "--plan", str(plan_path), "--execute", "--run-dir", str(run_dir), "--cwd", str(proj)]
            with patch.object(sys, "argv", argv), patch.object(lane_run.subprocess, "run", side_effect=fake_run), patch("sys.stdout", buf):
                lane_run.main()
            parsed = json.loads(buf.getvalue())
            by = {r["kind"]: r["status"] for r in parsed["results"]}
            self.assertTrue(str(by.get("impl", "")).startswith("exit"))
            self.assertEqual(by.get("review"), "blocked")

    def test_cli_main_reads_prompt_file(self):
        data = probe("grok")
        with tempfile.TemporaryDirectory() as td:
            prompt = Path(td) / "p.txt"
            probe_path = Path(td) / "probe.json"
            prompt.write_text(self.MIXED, encoding="utf-8")
            probe_path.write_text(json.dumps(data), encoding="utf-8")
            import subprocess
            out = subprocess.check_output(
                [sys.executable, str(SCRIPTS / "plan.py"), "--prompt-file", str(prompt), "--probe-json", str(probe_path), "--host", "grok"],
                text=True,
            )
            parsed = json.loads(out)
            self.assertIn("impl", kinds(parsed))

    def test_function_docs_is_write_not_impl(self):
        p = plan.build_plan("함수 설명을 README에 써줘", probe("grok"), "run")
        self.assertNotIn("impl", kinds(p))
        self.assertIn("write", kinds(p))

    def test_deploy_guide_is_write_not_impl(self):
        p = plan.build_plan("배포 가이드 초안 써줘", probe("grok"), "run")
        self.assertNotIn("impl", kinds(p))
        self.assertIn("write", kinds(p))

    def test_design_doc_is_write_not_hard(self):
        p = plan.build_plan("설계 문서 초안 써줘", probe("grok"), "run")
        self.assertNotIn("hard", kinds(p))
        self.assertIn("write", kinds(p))

    def test_english_and_splits(self):
        p = plan.build_plan("fix the bug and polish the readme", probe("grok"), "run")
        self.assertIn("impl", kinds(p))
        self.assertIn("write", kinds(p))
        self.assertNotIn("readme", item(p, "impl")["spec"].lower())

    def test_default_run_dir_is_timestamp(self):
        import os
        import subprocess
        data = probe("claude", in_orca=False)
        p = plan.build_plan("카피 다듬어 줘", data, "run")
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / "plan.json"
            proj = Path(td) / "proj"
            proj.mkdir()
            plan_path.write_text(json.dumps(p), encoding="utf-8")
            env = os.environ.copy()
            env["HOME"] = td
            out = subprocess.check_output(
                [sys.executable, str(SCRIPTS / "run.py"), "--plan", str(plan_path), "--cwd", str(proj)],
                text=True,
                env=env,
            )
            parsed = json.loads(out)
            name = Path(parsed["run_dir"]).name
            self.assertNotEqual(name, "current")
            self.assertTrue(name[0].isdigit())
            self.assertTrue(Path(parsed["run_dir"], "STATUS.md").is_file())

    def test_refuses_skill_package_as_implicit_cwd(self):
        import subprocess
        data = probe("claude", in_orca=False)
        p = plan.build_plan("카피 다듬어 줘", data, "run")
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / "plan.json"
            run_dir = Path(td) / "run"
            plan_path.write_text(json.dumps(p), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "--plan",
                    str(plan_path),
                    "--run-dir",
                    str(run_dir),
                ],
                cwd=str(SCRIPTS.parent),
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("--cwd", completed.stderr)

    def test_refuses_run_dir_named_current(self):
        import subprocess
        data = probe("claude", in_orca=False)
        p = plan.build_plan("카피 다듬어 줘", data, "run")
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / "plan.json"
            proj = Path(td) / "proj"
            proj.mkdir()
            plan_path.write_text(json.dumps(p), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "--plan",
                    str(plan_path),
                    "--run-dir",
                    str(Path(td) / "current"),
                    "--cwd",
                    str(proj),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("current", completed.stderr)

    def test_orca_supervise_uses_worker_start(self):
        import subprocess
        p = plan.build_plan("버그 고쳐 줘", probe("grok", in_orca=True), "run")
        self.assertTrue(p["supervise"])
        self.assertEqual(item(p, "impl")["via"], "orca")
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / "plan.json"
            run_dir = Path(td) / "run"
            proj = Path(td) / "proj"
            proj.mkdir()
            plan_path.write_text(json.dumps(p), encoding="utf-8")
            out = subprocess.check_output(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "--plan",
                    str(plan_path),
                    "--run-dir",
                    str(run_dir),
                    "--cwd",
                    str(proj),
                ],
                text=True,
            )
            parsed = json.loads(out)
            impl = next(r for r in parsed["results"] if r["kind"] == "impl")
            self.assertIn("worker-start", impl["argv"])
            self.assertTrue(any("worker-start" in step for step in impl["steps"]))

    def test_orca_handoff_uses_worktree_create(self):
        import subprocess
        data = probe("grok", in_orca=True)
        data["SUPERVISE"] = False
        p = plan.build_plan("버그 고쳐 줘", data, "run")
        self.assertFalse(p["supervise"])
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / "plan.json"
            run_dir = Path(td) / "run"
            proj = Path(td) / "proj"
            proj.mkdir()
            plan_path.write_text(json.dumps(p), encoding="utf-8")
            out = subprocess.check_output(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "--plan",
                    str(plan_path),
                    "--run-dir",
                    str(run_dir),
                    "--cwd",
                    str(proj),
                ],
                text=True,
            )
            parsed = json.loads(out)
            impl = next(r for r in parsed["results"] if r["kind"] == "impl")
            self.assertEqual(impl["argv"][1], "worktree")
            self.assertFalse(any("Do ONLY this impl" in a for a in impl["argv"]))

    def test_overlay_fills_claude_without_orca(self):
        import probe as lane_probe
        parsed = {}
        usage = {
            "claude": {"error": False, "fiveHourPercent": 40, "sevenDayPercent": 10},
            "codex": {"error": False, "fiveHourPercent": 20, "sevenDayPercent": 80},
        }
        out = lane_probe.overlay_cli_limits(parsed, usage)
        self.assertEqual(out["claude"]["session_pct"], 40)
        self.assertEqual(out["codex"]["weekly_pct"], 80)

    def test_overlay_does_not_clobber_orca(self):
        import probe as lane_probe
        parsed = {"claude": {"session_pct": 11, "session": "11%"}}
        usage = {"claude": {"error": False, "fiveHourPercent": 99}}
        out = lane_probe.overlay_cli_limits(parsed, usage)
        self.assertEqual(out["claude"]["session_pct"], 11)

    def test_skill_md_avoids_fixed_run_dir(self):
        text = (SCRIPTS.parent / "SKILL.md").read_text()
        self.assertNotIn("runs/current", text)
        self.assertNotIn("/tmp/lane-plan.json", text)

    def test_dispatch_md_no_cat_prompt(self):
        text = (SCRIPTS.parent / "references" / "dispatch.md").read_text()
        self.assertNotIn("$(cat", text)


if __name__ == "__main__":
    unittest.main()
