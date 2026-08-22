#!/usr/bin/env python3
"""Classify a prompt into lane items, apply limit gates, print a JSON plan."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
import probe  # noqa: E402

KIND_PATTERNS = {
    "impl": (
        r"구현", r"고치", r"고쳐", r"수정", r"버그", r"테스트 코드", r"테스트 추가",
        r"배포해", r"배포 해", r"배포하", r"코딩", r"컴포넌트", r"패치", r"기능 추가", r"코드 추가",
        r"함수 추가", r"함수를 추가", r"함수 만들", r"함수 구현",
        r"만들어 줘", r"만들어줘", r"harvest", r"\bfix\b", r"\bbug\b", r"implement",
        r"refactor", r"\btests?\b", r"\bdeploy\b", r"\bpatch\b",
    ),
    "write": (
        r"문서", r"카피", r"위키", r"윤문", r"초안", r"readme", r"\bdocs\b",
        r"카피라이팅", r"설명문", r"summar", r"\bdraft\b", r"합성",
        r"글쓰기", r"본문",
    ),
    "review": (
        r"리뷰", r"검수", r"2차", r"\breview\b",
    ),
    "hard": (
        r"아키텍처", r"보안", r"고위험", r"architecture", r"stuck",
        r"deadlock", r"cve", r"threat",
        r"설계(?!\s*(문서|초안|가이드))",
    ),
    "research": (
        r"조사", r"리서치", r"논문", r"다국어", r"research", r"survey", r"paper",
    ),
    "mechanical": (
        r"rename", r"포맷", r"format", r"lint", r"검색만",
    ),
}

KIND_TO_LANE = {
    "write": "write",
    "review": "write",
    "impl": "impl",
    "mechanical": "impl",
    "hard": "hard",
    "research": "research",
}

HOST_LANE = {
    "grok": "write",
    "codex": "impl",
    "claude": "hard",
    "gemini": "research",
    "hermes": "research",
    "minimax": None,
    "cursor": "impl",
    "opencode": "impl",
}

REVIEW_FALLBACK = ("grok", "claude")


def compile_kind() -> dict[str, re.Pattern]:
    return {kind: re.compile("|".join(pats), re.I) for kind, pats in KIND_PATTERNS.items()}


COMPILED = compile_kind()


def detect_kinds(text: str, host: str = "unknown") -> list[str]:
    found: list[str] = []
    for kind in ("impl", "mechanical", "write", "review", "hard", "research"):
        if COMPILED[kind].search(text):
            found.append(kind)
    if "mechanical" in found and "impl" in found:
        found.remove("mechanical")
    if "review" in found and "hard" in found:
        found.remove("review")
    if found:
        return found
    hl = HOST_LANE.get(host)
    if hl == "impl":
        return ["impl"]
    if hl == "hard":
        return ["hard"]
    if hl == "research":
        return ["research"]
    return ["write"]


def goal_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    line = re.sub(r"^/lane\s+(plan\s+)?", "", line, flags=re.I).strip()
    return line[:160] or "untitled"


def split_clauses(text: str) -> list[str]:
    cleaned = re.sub(r"^/lane\s+(plan\s+)?", "", text.strip(), flags=re.I)
    parts = re.split(
        r"\s*,\s*|\s+그리고\s+|\s+및\s+|\s+and\s+|\n+|(?<=고치고)\s+|(?<=하고)\s+|(?<=해서)\s+|(?<=[가-힣]고)\s+",
        cleaned,
    )
    return [p.strip() for p in parts if p.strip()]


def item_spec(text: str, kind: str) -> str:
    hits = [c for c in split_clauses(text) if COMPILED[kind].search(c)]
    body = " ".join(hits) if hits else text.strip()
    body = re.sub(r"\s+", " ", body)[:800]
    return (
        f"Do ONLY this {kind} work. Do not perform other parts of the original request.\n"
        f"{body}"
    )


def parse_pct(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    m = re.match(r"(\d+)", str(value))
    return int(m.group(1)) if m else None


def limits_known(data: dict) -> bool:
    limits = data.get("LIMITS") or {}
    if not limits or limits.get("error"):
        return False
    return any(isinstance(v, dict) and (v.get("weekly_pct") is not None or v.get("session_pct") is not None) for v in limits.values())


def provider_limit_known(data: dict, provider: str) -> bool:
    limits = data.get("LIMITS") or {}
    if not limits or limits.get("error"):
        return False
    block = limits.get(provider) if isinstance(limits.get(provider), dict) else {}
    if provider == "codex":
        return block.get("weekly_pct") is not None
    if provider == "claude":
        return block.get("session_pct") is not None or block.get("weekly_pct") is not None
    if provider == "grok":
        return block.get("weekly_pct") is not None
    return True


def via_for(
    kind_lane: str,
    provider: str,
    bin_path: str,
    host: str,
    orca: str,
    in_orca: bool,
) -> tuple[str, str]:
    if bin_path == "missing":
        return "skip", f"no {provider} binary"
    host_lane = HOST_LANE.get(host)
    if host_lane == kind_lane:
        return "here", "host already on this lane"
    if in_orca and orca == "ready" and provider in {"grok", "codex", "claude"}:
        return "orca", "orca worker-start"
    return "cli", f"{provider} cli"


def pick_review_provider(impl_provider: str, data: dict) -> tuple[str, str]:
    lanes = data.get("LANES") or {}
    for name in REVIEW_FALLBACK:
        if name == impl_provider:
            continue
        spec = None
        for lane_spec in lanes.values():
            if isinstance(lane_spec, dict) and lane_spec.get("provider") == name:
                spec = lane_spec
                break
        bin_path = (spec or {}).get("bin") or probe.which(name) or "missing"
        if bin_path != "missing":
            return name, bin_path
    return impl_provider, (lanes.get("write") or {}).get("bin") or "missing"


def apply_gates(item: dict, data: dict) -> dict:
    limits = data.get("LIMITS") or {}
    skip_at = int(data.get("CLAUDE_SESSION_SKIP_AT", 90))
    grok_skip_at = int(data.get("GROK_WEEKLY_SKIP_AT", 90))
    never = {n.lower() for n in (data.get("NEVER_ASSIGN") or [])}
    provider = item["provider"]
    if provider.lower() in never or item["kind"] in never:
        item["via"] = "skip"
        item["reason"] = f"{provider} is never_assign"
        return item
    if item["via"] in {"cli", "orca"} and item["kind"] in {"impl", "mechanical", "hard"}:
        need = "codex" if item["kind"] in {"impl", "mechanical"} else "claude"
        if not provider_limit_known(data, need):
            item["via"] = "skip"
            item["reason"] = f"{need} limits unknown; fail closed"
            return item
    if item["kind"] in {"impl", "mechanical"} and data.get("NEVER_SPILL_IMPL_TO_CLAUDE"):
        weekly = parse_pct((limits.get("codex") or {}).get("weekly_pct"))
        if weekly is not None and weekly >= 100:
            item["via"] = "skip"
            item["reason"] = "codex weekly 100%; do not spill impl to claude"
            return item
    if item["kind"] == "hard":
        session = parse_pct((limits.get("claude") or {}).get("session_pct"))
        if session is not None and session >= skip_at:
            item["via"] = "skip"
            item["reason"] = f"claude session {session}% >= {skip_at}"
            return item
    if item["kind"] in {"write", "review"} and item["via"] in {"cli", "orca"} and provider == "grok":
        weekly = parse_pct((limits.get("grok") or {}).get("weekly_pct"))
        if weekly is not None and weekly >= grok_skip_at:
            item["via"] = "skip"
            item["reason"] = f"grok weekly {weekly}% >= {grok_skip_at}"
            return item
    return item


def attach_needs(items: list[dict]) -> None:
    kinds = {i["kind"] for i in items}
    impl_skipped = any(i["kind"] == "impl" and i["via"] == "skip" for i in items)
    for item in items:
        needs: list[str] = []
        if item["kind"] in {"review", "hard"} and "impl" in kinds and not impl_skipped:
            needs.append("impl")
        item["needs"] = needs


def separate_review_vendor(items: list[dict], data: dict, host: str, orca: str, in_orca: bool) -> None:
    impl = next((i for i in items if i["kind"] == "impl"), None)
    review = next((i for i in items if i["kind"] == "review"), None)
    if not review:
        return
    forbidden = set()
    if impl:
        forbidden.add(impl["provider"])
    if host in {"grok", "claude", "codex"}:
        forbidden.add(host)
    if review["provider"] not in forbidden and review["via"] != "here":
        return
    if review["provider"] not in forbidden and review["via"] == "here" and host not in forbidden:
        return
    name, bin_path = pick_review_provider((impl or {}).get("provider") or "", data)
    if name in forbidden:
        for candidate in REVIEW_FALLBACK:
            if candidate in forbidden:
                continue
            bin_path = probe.which(candidate) or "missing"
            if bin_path != "missing":
                name = candidate
                break
        else:
            review["via"] = "skip"
            review["reason"] = "no independent review vendor"
            return
    review["provider"] = name
    review["lane"] = "write" if name == "grok" else "hard"
    via, reason = via_for(review["lane"], name, bin_path, host, orca, in_orca)
    if via == "here" and host in forbidden:
        via, reason = "cli", f"{name} cli"
    review["via"] = via
    review["reason"] = f"review vendor split from {','.join(sorted(forbidden)) or 'host'}; {reason}"


def build_plan(text: str, data: dict, mode: str) -> dict:
    host = data.get("HOST") or "unknown"
    orca = data.get("ORCA") or "missing"
    in_orca = bool(data.get("IN_ORCA"))
    kinds = detect_kinds(text, host)
    items = []
    for kind in kinds:
        lane_key = KIND_TO_LANE[kind]
        spec = (data.get("LANES") or {}).get(lane_key) or {}
        provider = spec.get("provider") or lane_key
        bin_path = spec.get("bin") or "missing"
        via, reason = via_for(lane_key, provider, bin_path, host, orca, in_orca)
        effort = spec.get("effort") or "default"
        if kind == "mechanical":
            effort = data.get("LANE_MECHANICAL_EFFORT") or "low"
        item = {
            "kind": kind,
            "lane": lane_key,
            "provider": provider,
            "via": via,
            "reason": reason,
            "effort": effort,
            "spec": item_spec(text, kind),
        }
        if spec.get("home"):
            item["home"] = spec["home"]
        items.append(apply_gates(item, data))
    separate_review_vendor(items, data, host, orca, in_orca)
    for item in items:
        apply_gates(item, data)
    attach_needs(items)
    return {
        "mode": mode,
        "goal": goal_line(text),
        "host": host,
        "orca": orca,
        "in_orca": in_orca,
        "supervise": bool(data.get("SUPERVISE", True)) and in_orca,
        "limits_known": limits_known(data),
        "approve_for_me": bool(data.get("APPROVE_FOR_ME", False)),
        "tokens": "kept on-lane" if len(items) == 1 and items[0]["via"] == "here" else "split",
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a /lane plan JSON")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prompt-file")
    parser.add_argument("--mode", choices=("plan", "run"), default="run")
    parser.add_argument("--host")
    parser.add_argument("--probe-json")
    args = parser.parse_args()
    text = args.prompt
    if args.prompt_file:
        text = Path(args.prompt_file).read_text()
    if not text.strip() and not sys.stdin.isatty():
        text = sys.stdin.read()
    if not text.strip():
        raise SystemExit("pass --prompt, --prompt-file, or stdin")
    if args.probe_json:
        data = json.loads(Path(args.probe_json).read_text())
    else:
        data = probe.collect()
    if args.host:
        data["HOST"] = args.host
    plan = build_plan(text, data, args.mode)
    json.dump(plan, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
