#!/usr/bin/env bash
# code-factory installer — vendor the factory into any repo.
#
#   ./install.sh <target-repo> [pack]
#
# Copies the engine (core/), the chosen pack (packs/<pack>/), a starter factory.config.yaml,
# the hook wiring (.claude/settings.json), and the activation surface (.claude/commands +
# .claude/agents from the pack's reviewers). After it runs, the Block layer fires automatically
# when you work in <target-repo> with Claude Code, and /ship-it + /factory-check are available.
#
# Re-runnable. Never clobbers an existing factory.config.yaml or .claude/settings.json — it
# writes a *.factory copy beside them and tells you to merge.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-}"
PACK="${2:-ts-next}"

if [ -z "$TARGET" ]; then
  echo "usage: ./install.sh <target-repo> [pack]   (packs: $(ls -m "$SRC/packs"))" >&2
  exit 2
fi
TARGET="$(cd "$TARGET" 2>/dev/null && pwd || true)"
[ -n "$TARGET" ] && [ -d "$TARGET" ] || { echo "target repo not found: ${1}" >&2; exit 2; }
[ -d "$SRC/packs/$PACK" ] || { echo "unknown pack '$PACK' (have: $(ls -m "$SRC/packs"))" >&2; exit 2; }

echo "Installing code-factory into $TARGET  (pack: $PACK)"

# 1. engine + pack (real files; -L resolves any symlinks in the source tree)
cp -RL "$SRC/core" "$TARGET/core"
mkdir -p "$TARGET/packs"
cp -RL "$SRC/packs/$PACK" "$TARGET/packs/$PACK"

# 2. config (don't clobber)
if [ -f "$TARGET/factory.config.yaml" ]; then
  echo "  ! factory.config.yaml exists — wrote factory.config.yaml.factory; merge 'packs:' yourself"
  DEST="$TARGET/factory.config.yaml.factory"
else
  DEST="$TARGET/factory.config.yaml"
fi
cat > "$DEST" <<YAML
# code-factory config. Core reads this from repo root.
packs:
  - $PACK
tracker: none
deploy: manual
base_branches:
  - main
issue_pattern: ""
YAML

# 3. hook wiring (don't clobber an existing settings.json)
mkdir -p "$TARGET/.claude"
if [ -f "$TARGET/.claude/settings.json" ]; then
  echo "  ! .claude/settings.json exists — wrote settings.json.factory; merge the hooks block"
  cp -L "$SRC/.claude/settings.json" "$TARGET/.claude/settings.json.factory"
else
  cp -L "$SRC/.claude/settings.json" "$TARGET/.claude/settings.json"
fi

# 4. activation: commands + agents as REAL files (self-contained in the target)
mkdir -p "$TARGET/.claude/commands" "$TARGET/.claude/agents"
cp -L "$SRC/core/commands/"*.md "$TARGET/.claude/commands/"
for f in "$TARGET/packs/$PACK/reviewers/"*-reviewer.md; do
  [ -e "$f" ] && cp -L "$f" "$TARGET/.claude/agents/$(basename "$f")"
done

# 5. gitignore the runtime ledger + python caches
if [ -f "$TARGET/.gitignore" ] && ! grep -q "^.claude/state/" "$TARGET/.gitignore"; then
  printf '\n# code-factory runtime ledger + caches\n.claude/state/\ncore/**/__pycache__/\n' >> "$TARGET/.gitignore"
fi

echo "Done. Verify: (cd \"$TARGET\" && bash core/selftest.sh)"
echo "Then work in the repo with Claude Code — gates fire automatically; run /factory-check and /ship-it."
