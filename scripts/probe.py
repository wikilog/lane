#!/usr/bin/env python3
"""Print host, binaries, merged lane config, and optional Orca limits. No secrets."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = SKILL_DIR / "references" / "default-config.json"
USER_CONFIG = Path.home() / ".config" / "lane" / "config.json"


def which(name: str) -> str:
    return shutil.which(name) or ""


def in_orca_terminal() -> bool:
    return bool(os.environ.get("ORCA_TERMINAL_HANDLE") or os.environ.get("ORCA_PANE_KEY"))


def env_host() -> str:
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
        return "claude"
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_INTERNAL_ORIGINATOR"):
        return "codex"
    if os.environ.get("GROK_AGENT") or os.environ.get("GROK_SESSION_ID") or os.environ.get("GROK_HOME"):
        return "grok"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_AGENT"):
        return "cursor"
    if os.environ.get("GEMINI_CLI"):
        return "gemini"
    if os.environ.get("OPENCODE"):
        return "opencode"
    hermes_home = os.environ.get("HERMES_HOME") or ""
    if hermes_home.rstrip("/").endswith("hermes-minimax") or os.environ.get("MINIMAX_AGENT"):
        return "minimax"
    if hermes_home.rstrip("/").endswith("hermes-qwen"):
        return "hermes"
    if hermes_home:
        return "hermes"
    return "unknown"


def run_json(args: list[str], timeout: int = 8) -> dict | None:
    try:
        raw = subprocess.check_output(args, stderr=subprocess.DEVNULL, timeout=timeout)
        return json.loads(raw)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return None


def git_root() -> Path | None:
    try:
        raw = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return Path(raw.decode().strip())
    except (OSError, subprocess.SubprocessError):
        return None


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_scalar(raw: str):
    s = raw.strip()
    if s in {"true", "True", "yes"}:
        return True
    if s in {"false", "False", "no"}:
        return False
    if s in {"null", "~", ""}:
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {'"', "'"}:
        return s[1:-1]
    try:
        if s.startswith("0") and len(s) > 1:
            raise ValueError
        return int(s)
    except ValueError:
        return s


def parse_simple_yaml(text: str) -> dict:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return _indent_yaml(text)


def _next_content(lines: list[str], start: int) -> str | None:
    for raw in lines[start:]:
        body = raw.split("#", 1)[0].rstrip()
        if body.strip():
            return body
    return None


def _indent_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        body = raw.split("#", 1)[0].rstrip()
        if not body.strip():
            continue
        indent = len(body) - len(body.lstrip(" "))
        stripped = body.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if stripped.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError(f"yaml list without a key at line {i + 1}")
            parent.append(_parse_scalar(stripped[2:]))
            continue
        if ":" not in stripped:
            raise ValueError(f"yaml line {i + 1}")
        if not isinstance(parent, dict):
            raise ValueError(f"yaml map under list at line {i + 1}")
        key, rest = stripped.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        if rest:
            parent[key] = _parse_scalar(rest)
            continue
        nxt = _next_content(lines, i + 1)
        child: dict | list
        if nxt is not None and nxt.strip().startswith("- ") and (len(nxt) - len(nxt.lstrip(" "))) > indent:
            child = []
        else:
            child = {}
        parent[key] = child
        stack.append((indent, child))
    return root


def load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = parse_simple_yaml(path.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def lanes_yaml_to_cfg(data: dict) -> dict:
    out: dict = {}
    for key in ("lanes", "fallbacks", "never_assign", "providers", "models", "effort"):
        if key in data:
            out[key] = data[key]
    if "pin" in data:
        models = dict(out.get("models") or {})
        models["pin"] = bool(data["pin"])
        out["models"] = models
    return out


def skillops_lanes_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get("SKILLOPS_LANES")
    if env:
        paths.append(Path(env).expanduser())
    paths.append(Path.home() / ".config" / "skillops" / "lanes.yaml")
    root = git_root()
    if root is not None and (root / ".skillops" / "manifest.yaml").is_file():
        paths.append(root / "profiles" / "lanes.yaml")
    return paths


def load_skillops_lanes() -> tuple[dict, str]:
    for path in skillops_lanes_paths():
        raw = load_yaml(path)
        cfg = lanes_yaml_to_cfg(raw)
        if cfg:
            return cfg, str(path)
    return {}, ""


def merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, val in overlay.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], val)
        else:
            out[key] = val
    return out


def pct(block: dict | None, key: str) -> str:
    if not isinstance(block, dict):
        return "-"
    inner = block.get(key)
    if not isinstance(inner, dict) or inner.get("usedPercent") is None:
        return "-"
    reset = inner.get("resetDescription") or ""
    return f"{inner['usedPercent']}%{(' ' + reset) if reset else ''}"


def expand(path: str) -> str:
    return str(Path(os.path.expanduser(path))) if path else ""


def parse_orca_limits(accounts: dict) -> dict:
    limits = (accounts.get("result") or {}).get("rateLimits") or {}
    parsed: dict = {}
    for name in ("claude", "codex", "grok"):
        block = limits.get(name) if isinstance(limits.get(name), dict) else None
        parsed[name] = {
            "session": pct(block, "session"),
            "weekly": pct(block, "weekly"),
            "session_pct": limit_pct(block, "session"),
            "weekly_pct": limit_pct(block, "weekly"),
        }
        if name == "codex" and isinstance(block, dict):
            credits = block.get("rateLimitResetCredits") or {}
            if isinstance(credits, dict) and credits.get("availableCount") is not None:
                parsed[name]["reset_credits"] = credits["availableCount"]
    return parsed


def _fill_pct(block: dict, key: str, value) -> None:
    if block.get(f"{key}_pct") is not None or value is None:
        return
    try:
        n = int(value)
    except (TypeError, ValueError):
        return
    block[f"{key}_pct"] = n
    block[key] = f"{n}%"


def overlay_cli_limits(parsed: dict, usage: dict) -> dict:
    out = dict(parsed)
    mapping = {
        "claude": ("fiveHourPercent", "sevenDayPercent"),
        "codex": ("fiveHourPercent", "sevenDayPercent"),
    }
    for name, (session_key, weekly_key) in mapping.items():
        row = usage.get(name)
        if not isinstance(row, dict) or row.get("error"):
            continue
        block = dict(out[name]) if isinstance(out.get(name), dict) else {}
        _fill_pct(block, "session", row.get(session_key))
        _fill_pct(block, "weekly", row.get(weekly_key))
        if block:
            out[name] = block
    return out


def load_cli_usage() -> dict:
    node = which("node")
    if not node:
        return {}
    root = Path.home() / ".claude" / "plugins" / "cache" / "claude-dashboard"
    matches = list(root.glob("claude-dashboard/*/dist/check-usage.js"))
    if not matches:
        return {}

    def ver(path: Path):
        try:
            return tuple(int(x) for x in path.parts[-3].split("."))
        except ValueError:
            return (0,)

    script = sorted(matches, key=ver)[-1]
    data = run_json([node, str(script), "--json"], timeout=12)
    return data if isinstance(data, dict) else {}


def resolve_research(cfg: dict) -> tuple[str, str, str]:
    providers = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    lane = (cfg.get("lanes") or {}).get("research") or "auto"
    if lane != "auto" and lane in providers:
        spec = providers[lane] if isinstance(providers[lane], dict) else {}
        bin_name = spec.get("bin") or lane
        home = expand(spec.get("home") or "")
        found = which(bin_name)
        return lane, found or "missing", home
    for name in ("gemini", "grok", "hermes"):  # hermes 기본 홈은 alibaba(무료 한도 소진)라 grok 다음
        found = which(name)
        if found:
            home = ""
            if name == "hermes" and isinstance(providers.get("hermes"), dict):
                home = expand(providers["hermes"].get("home") or "")
            return name, found, home
    return "research", "missing", ""


def limit_pct(block: dict | None, key: str) -> int | None:
    if not isinstance(block, dict):
        return None
    inner = block.get(key)
    if not isinstance(inner, dict) or inner.get("usedPercent") is None:
        return None
    try:
        return int(inner["usedPercent"])
    except (TypeError, ValueError):
        return None


def collect() -> dict:
    sources = ["default"]
    cfg = load_json(DEFAULT_CONFIG)
    skillops, skillops_path = load_skillops_lanes()
    if skillops:
        cfg = merge(cfg, skillops)
        sources.append("skillops")
        out_skillops = skillops_path
    else:
        out_skillops = ""
    user = load_json(USER_CONFIG)
    if user:
        cfg = merge(cfg, user)
        sources.append("user")
    root = git_root()
    if root is not None:
        project = load_json(root / ".lane.json")
        if project:
            cfg = merge(cfg, project)
            sources.append("project")

    bins = ("orca", "codex", "claude", "grok", "gemini", "hermes", "cursor", "opencode")
    bin_map = {name: which(name) or "missing" for name in bins}

    lanes = cfg.get("lanes") if isinstance(cfg.get("lanes"), dict) else {}
    effort = cfg.get("effort") if isinstance(cfg.get("effort"), dict) else {}
    research_name, research_bin, research_home = resolve_research(cfg)
    providers_cfg = cfg.get("providers") if isinstance(cfg.get("providers"), dict) else {}
    providers: dict = {}
    for name, spec in providers_cfg.items():
        if not isinstance(spec, dict):
            continue
        bin_name = spec.get("bin") or name
        providers[name] = {
            "bin": bin_map.get(bin_name) or which(bin_name) or "missing",
            "home": expand(spec.get("home") or ""),
        }

    out: dict = {
        "SKILL_DIR": str(SKILL_DIR),
        "CONFIG_SOURCES": "+".join(sources),
        "SKILLOPS_LANES": out_skillops,
        "HOST": env_host(),
        "REPO": str(root) if root else "-",
        "CLAUDE_SESSION_SKIP_AT": int(cfg.get("claude_session_skip_at", 90)),
        "GROK_WEEKLY_SKIP_AT": int(cfg.get("grok_weekly_skip_at", 90)),
        "NEVER_SPILL_IMPL_TO_CLAUDE": bool(cfg.get("never_spill_impl_to_claude", True)),
        "NEVER_ASSIGN": [str(x) for x in (cfg.get("never_assign") or [])],
        "BINS": bin_map,
        "LANES": {
            "write": {
                "provider": lanes.get("write", "grok"),
                "bin": bin_map.get(lanes.get("write", "grok"), which(lanes.get("write", "grok")) or "missing"),
                "effort": effort.get("write", "default"),
            },
            "impl": {
                "provider": lanes.get("impl", "codex"),
                "bin": bin_map.get(lanes.get("impl", "codex"), which(lanes.get("impl", "codex")) or "missing"),
                "effort": effort.get("impl", "medium"),
            },
            "hard": {
                "provider": lanes.get("hard", "claude"),
                "bin": bin_map.get(lanes.get("hard", "claude"), which(lanes.get("hard", "claude")) or "missing"),
                "effort": effort.get("hard", "high"),
            },
            "research": {
                "provider": research_name,
                "bin": research_bin,
                "home": research_home,
                "effort": "default",
            },
        },
        "LANE_MECHANICAL_EFFORT": effort.get("mechanical", "low"),
        "FALLBACKS": cfg.get("fallbacks") if isinstance(cfg.get("fallbacks"), dict) else {},
        "PROVIDERS": providers,
        "MODELS": cfg.get("models") if isinstance(cfg.get("models"), dict) else {},
        "IN_ORCA": in_orca_terminal(),
        "ORCA": "missing" if bin_map["orca"] == "missing" else "down",
        "APPROVE_FOR_ME": bool(cfg.get("approve_for_me", False)),
        "SUPERVISE": bool(cfg.get("supervise_default", True)),
        "LIMITS": {},
    }

    parsed: dict = {}
    limit_sources: list[str] = []
    if bin_map["orca"] != "missing":
        status = run_json(["orca", "status", "--json"])
        if isinstance(status, dict) and status.get("ok"):
            runtime = ((status.get("result") or {}).get("runtime") or {})
            out["ORCA"] = "ready" if runtime.get("reachable") else "down"
            if runtime.get("appVersion"):
                out["ORCA_VERSION"] = runtime["appVersion"]
        accounts = run_json(["orca", "account", "list", "--json"])
        if isinstance(accounts, dict) and accounts.get("ok"):
            parsed = parse_orca_limits(accounts)
            if parsed:
                limit_sources.append("orca")
    usage = load_cli_usage()
    if usage:
        before = json.dumps(parsed, sort_keys=True)
        parsed = overlay_cli_limits(parsed, usage)
        if json.dumps(parsed, sort_keys=True) != before:
            limit_sources.append("cli")
    if parsed:
        out["LIMITS"] = parsed
        out["LIMITS_SOURCE"] = "+".join(limit_sources)
    elif bin_map["orca"] != "missing":
        out["LIMITS"] = {"error": "unavailable"}
    return out


def print_kv(data: dict) -> None:
    print(f"SKILL_DIR={data['SKILL_DIR']}")
    print(f"CONFIG_SOURCES={data['CONFIG_SOURCES']}")
    print(f"HOST={data['HOST']}")
    print(f"REPO={data['REPO']}")
    print(f"CLAUDE_SESSION_SKIP_AT={data['CLAUDE_SESSION_SKIP_AT']}")
    print(f"GROK_WEEKLY_SKIP_AT={data.get('GROK_WEEKLY_SKIP_AT', 90)}")
    print(f"NEVER_SPILL_IMPL_TO_CLAUDE={data['NEVER_SPILL_IMPL_TO_CLAUDE']}")
    never = data.get("NEVER_ASSIGN") or []
    if never:
        print(f"NEVER_ASSIGN={','.join(never)}")
    for name, path in (data.get("BINS") or {}).items():
        print(f"BIN_{name.upper()}={path}")
    for kind, spec in (data.get("LANES") or {}).items():
        print(f"LANE_{kind.upper()}={spec['provider']}")
        print(f"LANE_{kind.upper()}_BIN={spec['bin']}")
        if spec.get("effort"):
            print(f"LANE_{kind.upper()}_EFFORT={spec['effort']}")
        if spec.get("home"):
            print(f"LANE_{kind.upper()}_HOME={spec['home']}")
    print(f"LANE_MECHANICAL_EFFORT={data.get('LANE_MECHANICAL_EFFORT', 'low')}")
    print(f"IN_ORCA={str(data.get('IN_ORCA', False)).lower()}")
    print(f"ORCA={data.get('ORCA')}")
    print(f"SUPERVISE={str(data.get('SUPERVISE', True)).lower()}")
    if data.get("ORCA_VERSION"):
        print(f"ORCA_VERSION={data['ORCA_VERSION']}")
    if data.get("LIMITS_SOURCE"):
        print(f"LIMITS_SOURCE={data['LIMITS_SOURCE']}")
    limits = data.get("LIMITS") or {}
    if limits.get("error"):
        print("LIMITS=unavailable")
        return
    for name, block in limits.items():
        if not isinstance(block, dict):
            continue
        print(f"LIMIT_{name.upper()}_SESSION={block.get('session', '-')}")
        print(f"LIMIT_{name.upper()}_WEEKLY={block.get('weekly', '-')}")
        if block.get("reset_credits") is not None:
            print(f"LIMIT_{name.upper()}_RESET_CREDITS={block['reset_credits']}")


def main() -> None:
    data = collect()
    if "--json" in sys.argv:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    print_kv(data)


if __name__ == "__main__":
    main()
