#!/usr/bin/env bash
# code-factory GLOBAL installer — run once. Makes /ship-it + /factory-check available in EVERY
# repo (symlinked to this checkout, like your ~/.claude/skills), and puts the `factory` CLI on
# PATH. The engine stays here; nothing is copied into your repos.
#
# Then, in any repo you want gated:   factory init        (drops config + hook wiring)
#
#   ./install-global.sh
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE="$HOME/.claude"
BIN="$HOME/.local/bin"

mkdir -p "$CLAUDE/commands" "$BIN"

# 1. slash commands -> global (symlink the canonical engine commands)
for c in "$SRC/core/commands/"*.md; do
  ln -sf "$c" "$CLAUDE/commands/$(basename "$c")"
  echo "  command: /$(basename "$c" .md)"
done

# 2. the factory CLI on PATH
ln -sf "$SRC/core/bin/factory" "$BIN/factory"
chmod +x "$SRC/core/bin/factory"
echo "  cli: $BIN/factory -> $SRC/core/bin/factory"

echo ""
echo "Global install done (engine: $SRC)."
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "NOTE: $BIN is not on your PATH. Add to your shell rc:  export PATH=\"$BIN:\$PATH\"" ;;
esac
echo ""
echo "Next: in any repo you want gated, run:  factory init"
echo "/ship-it and /factory-check are now available in every repo."
