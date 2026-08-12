#!/usr/bin/env bash
# code-factory self-test runner.
# Runs `--selftest` on every core module that supports it, plus the reviewer fleet
# self-test. Non-zero exit if anything fails.
#
# Usage:  bash core/selftest.sh
set -uo pipefail

CORE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$CORE_DIR/.." && pwd)"
fails=0
ran=0

echo "=== code-factory self-test ==="
echo

# every *.py under core/ that declares a --selftest path
while IFS= read -r f; do
  if grep -q -- "--selftest" "$f"; then
    name="${f#"$ROOT"/}"
    echo "--- $name ---"
    if python3 "$f" --selftest; then :; else fails=$((fails + 1)); fi
    ran=$((ran + 1))
    echo
  fi
done < <(find "$CORE_DIR" -name "*.py" | sort)

# commands sanity — the factory command set must exist
echo "--- commands sanity ---"
CMD_DIR="$CORE_DIR/commands"
for c in ship-it factory-check; do
  if [ -f "$CMD_DIR/$c.md" ]; then
    echo "  [PASS] /$c"
  else
    echo "  [FAIL] /$c missing"; fails=$((fails + 1))
  fi
done
ran=$((ran + 1))
echo

echo "=== ran $ran self-test module(s); $fails failed ==="
[ "$fails" -eq 0 ] || exit 1
