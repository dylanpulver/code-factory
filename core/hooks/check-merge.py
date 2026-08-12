#!/usr/bin/env python3
"""
check-merge — merge gate (PreToolUse: Bash on `gh pr merge`).

Print the pre-merge checklist. Hard-block `--admin` (bypasses branch protection) unless
FACTORY_MERGE_OK=1. Pure logic in `check()`.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

CHECKLIST = (
    "Pre-merge checklist:\n"
    "  - factory-check green (tsc/build + lint + tests + standards)?\n"
    "  - review loop clean (no surviving P1/P2)?\n"
    "  - per-surface QA done / validation ledger complete?\n"
    "  - any schema/data migration applied + verified BEFORE merging dependent code?\n"
    "  - PR body references the issue(s) it spans (if an issue_pattern is configured)?"
)


def check(cmd: str, merge_ok: bool):
    """Return ('ok'|'block'|'note', reason). 'note' = print checklist, allow."""
    sub, args = fx.cli_subcommand(cmd, "gh")
    if not (sub == "pr" and args and args[0] == "merge"):  # catches `gh -R o/r pr merge`
        return "ok", ""
    if re.search(r"--admin\b", cmd or "") and not merge_ok:
        return "block", ("`gh pr merge --admin` bypasses branch protection. Set FACTORY_MERGE_OK=1 to "
                         "do this deliberately.\n" + CHECKLIST)
    return "note", CHECKLIST


def main(data):
    verdict, reason = check(fx.command(data), fx.flag("FACTORY_MERGE_OK"))
    if verdict == "block":
        fx.emit_block("check-merge: " + reason)
    elif verdict == "note":
        fx.emit_warn("check-merge — " + reason)


def _selftest() -> int:
    fails = 0

    def case(name, cmd, merge_ok, expect):
        nonlocal fails
        got, _ = check(cmd, merge_ok)
        ok = got == expect
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {got} (want {expect})")

    case("plain merge -> note", "gh pr merge 123 --squash", False, "note")
    case("admin without override blocked", "gh pr merge 123 --admin --squash", False, "block")
    case("admin with override -> note", "gh pr merge 123 --admin --squash", True, "note")
    case("gh -R o/r pr merge --admin blocked", "gh -R o/r pr merge 123 --admin", False, "block")
    case("non-merge skipped", "gh pr view 123", False, "ok")

    print(f"\ncheck-merge.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    fx.run(main)
