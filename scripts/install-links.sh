#!/usr/bin/env bash
# Point agent skill roots (and ~/skills/library/lane) at this clone.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ ! -f "$ROOT/SKILL.md" ]]; then
  echo "error: $ROOT/SKILL.md missing" >&2
  exit 1
fi
mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.grok/skills" "$HOME/skills/library" \
  "$HOME/.grok/rules" "$HOME/.claude/rules"
for dest in \
  "$HOME/.agents/skills/lane" \
  "$HOME/.claude/skills/lane" \
  "$HOME/.codex/skills/lane" \
  "$HOME/.grok/skills/lane"
do
  ln -sfn "$ROOT" "$dest"
  echo "linked $dest -> $ROOT"
done
hub="$HOME/skills/library/lane"
if [[ -L "$hub" || -d "$hub" ]]; then
  if [[ -d "$hub" && ! -L "$hub" ]]; then
    bak="$HOME/skills/library/lane.bak-$(date +%Y%m%d%H%M%S)"
    mv "$hub" "$bak"
    echo "moved $hub -> $bak"
  else
    rm -f "$hub"
  fi
fi
ln -sfn "$ROOT" "$hub"
echo "linked $hub -> $ROOT"
for dest in "$HOME/.grok/rules/lane.md" "$HOME/.claude/rules/lane.md"
do
  ln -sfn "$ROOT/always-on.md" "$dest"
  echo "linked $dest -> $ROOT/always-on.md"
done
python3 - <<PY
from pathlib import Path
root = Path("$ROOT").resolve()
for p in [
    Path.home()/".agents/skills/lane",
    Path.home()/".claude/skills/lane",
    Path.home()/".codex/skills/lane",
    Path.home()/".grok/skills/lane",
    Path.home()/"skills/library/lane",
]:
    print(p, "->", p.resolve())
    assert p.resolve() == root, p
for p in [Path.home()/".grok/rules/lane.md", Path.home()/".claude/rules/lane.md"]:
    print(p, "->", p.resolve())
    assert p.resolve() == root / "always-on.md", p
print("ok: one clone")
PY
