#!/usr/bin/env python3
"""Refresh lane model aliases from local CLI catalogs + public docs. Stdlib only."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS.parent
USER_CONFIG = Path.home() / ".config" / "lane" / "config.json"
SNAPSHOT = Path.home() / ".config" / "lane" / "model-snapshot.json"
MATRIX = Path.home() / "skills" / "library" / "route-model" / "references" / "model-matrix.md"
HERMES_JOBS = Path.home() / ".hermes" / "cron" / "jobs.json"
JOB_NAME = "lane-model-refresh"
JOB_ID = "a15d0de1c0de"

SOURCES = {
    "claude": "https://platform.claude.com/docs/en/about-claude/models/overview",
    "openai": "https://openai.com/index/gpt-5-6/",
    "qwen": "https://qwen.ai/blog?id=qwen3.8",
}

UA = "lane-model-refresh/1.0 (+local catalog first)"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(200_000)
    return raw.decode("utf-8", "replace")


def grok_default(catalog: dict) -> str | None:
    models = catalog.get("models") if isinstance(catalog, dict) else None
    if not isinstance(models, dict):
        return None
    visible: list[str] = []
    for slug, block in models.items():
        info = (block or {}).get("info") if isinstance(block, dict) else {}
        if not isinstance(info, dict) or info.get("hidden"):
            continue
        desc = str(info.get("description") or "").lower()
        if "latest" in desc:
            return slug
        visible.append(slug)

    def ver(slug: str) -> tuple[int, int]:
        m = re.search(r"grok-(\d+)\.(\d+)", slug)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    return max(visible, key=ver) if visible else None


def grok_default_from_text(text: str) -> str | None:
    m = re.search(r"Default model:\s+(\S+)", text)
    if m:
        return m.group(1).strip()
    ids = re.findall(r"^\s*[\*\-]\s+(grok-[\w.\-]+)", text, re.M)
    return ids[0] if ids else None


def codex_slugs(cache: dict) -> list[str]:
    models = cache.get("models") if isinstance(cache, dict) else None
    if not isinstance(models, list):
        return []
    out = []
    for row in models:
        if isinstance(row, dict) and row.get("slug"):
            out.append(str(row["slug"]))
    return out


def pick_codex_default(slugs: list[str]) -> str | None:
    for slug in slugs:
        if re.search(r"sol$", slug, re.I):
            return slug
    return slugs[0] if slugs else None


def pick_codex_cheap(slugs: list[str]) -> str | None:
    for slug in slugs:
        if re.search(r"luna$", slug, re.I):
            return slug
    for slug in slugs:
        if re.search(r"mini", slug, re.I):
            return slug
    return None


def scan_claude(html: str) -> dict:
    found: dict[str, str] = {}
    if re.search(r"claude[- ]fable[- ]?5", html, re.I):
        found["fable"] = "fable"
    if re.search(r"claude[- ]opus[- ]?5", html, re.I):
        found["opus"] = "opus"
    if re.search(r"claude[- ]sonnet[- ]?5", html, re.I):
        found["sonnet"] = "sonnet"
    if re.search(r"claude[- ]haiku", html, re.I):
        found["haiku"] = "haiku"
    return found


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def collect(offline: bool = False) -> dict:
    notes: list[str] = []
    observed = {
        "grok_default": None,
        "codex_default": None,
        "codex_cheap": None,
        "claude_hard": "opus",
        "claude_default": "sonnet",
        "qwen": "qwen3.8-max",
        "minimax": "MiniMax-M3",
    }
    grok_cache = load_json(Path.home() / ".grok" / "models_cache.json")
    grok = grok_default(grok_cache)
    if grok:
        observed["grok_default"] = grok
        notes.append(f"grok catalog: {grok}")
    else:
        try:
            raw = subprocess.check_output(["grok", "models"], stderr=subprocess.DEVNULL, timeout=8, text=True)
            grok = grok_default_from_text(raw)
            if grok:
                observed["grok_default"] = grok
                notes.append(f"grok models: {grok}")
        except (OSError, subprocess.SubprocessError):
            notes.append("grok catalog unavailable")

    codex_cache = load_json(Path.home() / ".codex" / "models_cache.json")
    slugs = codex_slugs(codex_cache)
    observed["codex_default"] = pick_codex_default(slugs)
    observed["codex_cheap"] = pick_codex_cheap(slugs)
    if slugs:
        notes.append("codex catalog: " + ",".join(slugs[:6]))

    web: dict[str, str] = {}
    if not offline:
        for name, url in SOURCES.items():
            try:
                body = fetch(url)
                web[name] = url
                if name == "claude":
                    aliases = scan_claude(body)
                    if aliases.get("opus"):
                        observed["claude_hard"] = aliases["opus"]
                    if aliases.get("sonnet"):
                        observed["claude_default"] = aliases["sonnet"]
                    notes.append("claude docs: " + ",".join(sorted(aliases)))
                if name == "qwen" and re.search(r"qwen3\.8-?max", body, re.I):
                    observed["qwen"] = "qwen3.8-max"
                    notes.append("qwen docs: qwen3.8-max")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                notes.append(f"{name} fetch failed: {exc.__class__.__name__}")
                web[name] = f"error:{exc.__class__.__name__}"

    return {
        "as_of": utc_now(),
        "pin": False,
        "observed": observed,
        "sources": {
            "local": {
                "grok": str(Path.home() / ".grok" / "models_cache.json"),
                "codex": str(Path.home() / ".codex" / "models_cache.json"),
            },
            "web": web,
        },
        "notes": notes,
        "routing": {
            "write": "grok family default (unpinned)",
            "impl": "codex family default (unpinned, sol-class)",
            "mechanical": observed.get("codex_cheap") or "codex cheap tier",
            "hard": "claude opus alias",
            "research": "grok (auto: gemini → grok → hermes)",
            "fallback_impl": "grok",
            "fallback_hard": "grok",
            "fallback_write": "codex",
        },
    }


def render_matrix(snap: dict) -> str:
    obs = snap.get("observed") or {}
    as_of = (snap.get("as_of") or "")[:10] or "unknown"
    return f"""# 모델·에이전트 매트릭스 (스냅샷 {as_of})

> `scripts/refresh_models.py`가 로컬 CLI 카탈로그 + 공개 문서를 읽어 15일마다 갱신한다.
> 런타임은 세대 번호를 고정하지 않는다. Claude `sonnet`/`opus`처럼 Grok·Codex도 CLI 기본값을 따른다.

## 함대 배정

| 봇 | 이름 | 런타임 | 강점 | 역할 |
|----|------|--------|------|------|
| hermes | Marcus | Grok CLI default (관측: {obs.get("grok_default") or "grok"}) | 지식 작업·오케스트레이션·리뷰 | 1순위 글쓰기·리뷰 |
| dewa | Dewa | Codex CLI default (관측: {obs.get("codex_default") or "sol-class"}) | 터미널·에이전트 코딩 | 1순위 구현 |
| orion | Orion | {obs.get("qwen") or "qwen3.8-max"} | 다국어 리서치·장시간 기획 | 쉼 (alibaba 무료 한도 소진, 2026-10-26) |
| maxi | Maxi | {obs.get("minimax") or "MiniMax-M3"} | 저비용 코딩·긴 컨텍스트 | 쉼 (사용 중단, 2026-10-26) |
| nova | Nova | — | — | 폐기 |

## 레인

| 레인 | 1순위 | 모델 지정 | 폴백 (한도 소진·바이너리 없음) |
|------|-------|-----------|--------------------------------|
| write | grok | 생략 (CLI default) | codex |
| review | grok | 생략 (CLI default) | codex → grok (impl 벤더 제외) |
| impl | codex | 생략 (CLI default) | grok |
| mechanical | codex | `{obs.get("codex_cheap") or "gpt-5.6-luna"}` (저비용 티어) | grok |
| hard | claude | `{obs.get("claude_hard") or "opus"}` 패밀리 별칭 | grok |
| research | auto (gemini → grok → hermes) | 홈 기본값 | grok |

Claude impl로 넘기지 않는다. MiniMax 호스트 세션은 코디네이터만 하고 `via=here` 워커가 되지 않는다.

## 8월 2026 관측 메모

- GPT-5.6 Sol: Terminal-Bench 2.1 88.8%, Coding Agent Index 80. 구현 1순위 유지.
- Grok 4.6: Intelligence Index에서 Sol과 동점대, 단가 낮음. DeepSWE·Terminal-Bench는 Sol이 앞섬 → 글/리뷰 1순위 유지.
- Claude: 패밀리 별칭 `sonnet`/`opus`. 문서상 Sonnet 5·Opus 5·Fable 5. hard는 opus (Fable은 단가 2배, 별칭 없음).
- Qwen 3.8-Max: PaperBench·OSWorld·장시간 에이전트. 리서치 1순위, 1차 폴백.
- MiniMax-M3: SWE·긴 컨텍스트·저비용. Qwen 다음 폴백. Maxi 봇에는 1순위 일을 넣지 않는다.

## effort

- 기계적 편집: low (+ cheap Codex 티어)
- 구현: medium
- hard: high
- xhigh: 명시 호출만
"""


def patch_user_config(snap: dict) -> None:
    cfg = load_json(USER_CONFIG)
    models = cfg.get("models") if isinstance(cfg.get("models"), dict) else {}
    models["pin"] = False
    obs = snap.get("observed") or {}
    if obs.get("claude_hard"):
        models["claude_hard"] = obs["claude_hard"]
    if obs.get("claude_default"):
        models["claude_default"] = obs["claude_default"]
    if obs.get("codex_cheap"):
        models["codex_mechanical"] = obs["codex_cheap"]
    models["observed"] = {k: v for k, v in obs.items() if v}
    models["as_of"] = snap.get("as_of")
    cfg["models"] = models
    USER_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    USER_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")


def write_snapshot(snap: dict) -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
    MATRIX.parent.mkdir(parents=True, exist_ok=True)
    MATRIX.write_text(render_matrix(snap))


def install_cron() -> str:
    jobs = load_json(HERMES_JOBS)
    lst = jobs.get("jobs") if isinstance(jobs.get("jobs"), list) else []
    existing = next((j for j in lst if isinstance(j, dict) and j.get("name") == JOB_NAME), None)
    wrap = Path.home() / ".hermes" / "scripts" / "wrap-lane-model-refresh.sh"
    job = {
        "id": JOB_ID,
        "name": JOB_NAME,
        "prompt": None,
        "skills": [],
        "skill": None,
        "model": None,
        "provider": None,
        "base_url": None,
        "script": wrap.name,
        "no_agent": True,
        "context_from": None,
        "schedule": {"kind": "cron", "expr": "0 9 1,16 * *", "display": "0 9 1,16 * *"},
        "schedule_display": "0 9 1,16 * *",
        "repeat": {"times": None, "completed": 0},
        "enabled": True,
        "state": "scheduled",
        "paused_at": None,
        "paused_reason": None,
        "created_at": datetime.now().astimezone().isoformat(),
        "next_run_at": None,
        "last_run_at": None,
        "last_status": None,
        "last_error": None,
        "last_delivery_error": None,
        "deliver": "discord:1494941228767248384",
        "origin": None,
        "enabled_toolsets": None,
        "workdir": None,
        "profile": None,
        "fire_claim": None,
    }
    if existing:
        existing.update({k: job[k] for k in ("script", "no_agent", "schedule", "schedule_display", "enabled", "state")})
        action = "updated"
    else:
        lst.append(job)
        jobs["jobs"] = lst
        action = "added"
    HERMES_JOBS.write_text(json.dumps(jobs, ensure_ascii=False, indent=2) + "\n")
    return f"{action} hermes cron {JOB_NAME} ({job['schedule_display']})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh lane model aliases")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--install-cron", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    snap = collect(offline=args.offline)
    if args.dry_run:
        json.dump(snap, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    write_snapshot(snap)
    patch_user_config(snap)
    print(f"wrote {SNAPSHOT}")
    print(f"wrote {MATRIX}")
    print(f"patched {USER_CONFIG}")
    if args.install_cron:
        print(install_cron())
    for note in snap.get("notes") or []:
        print(f"- {note}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
