#!/usr/bin/env python3
"""
check-pr-create — PR-link gate (PreToolUse: Bash on `gh pr create`).

Enforce "no issue, no PR" ONLY when an `issue_pattern` is configured (default off — most
repos don't require a tracker link). When set, block `gh pr create` unless an id matching the
pattern appears in the PR title/body/body-file/--fill commits. Pure logic in `check()`.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402


def _arg(cmd, flag):
    m = re.search(rf"{flag}\s+(\"([^\"]*)\"|'([^']*)'|(\S+))", cmd)
    if not m:
        return None
    return next((g for g in m.groups()[1:] if g is not None), None)


def _is_pr_create(cmd: str) -> bool:
    sub, args = fx.cli_subcommand(cmd, "gh")  # catches `gh -R o/r pr create`
    return sub == "pr" and bool(args) and args[0] == "create"


def check(cmd: str, pattern: str, body_file_text: str = "", commit_log_text: str = ""):
    """Return ('ok'|'block', reason). pattern='' disables the gate (always ok)."""
    if not _is_pr_create(cmd):
        return "ok", ""
    if not pattern:
        return "ok", ""
    try:
        issue = re.compile(pattern)
    except re.error:
        return "ok", ""  # fail-safe: a bad pattern never blocks
    haystacks = []
    for flag in ("--body", "--title"):
        v = _arg(cmd, flag)
        if v:
            haystacks.append(v)
    if "--body-file" in cmd or "-F" in cmd:
        haystacks.append(body_file_text)
    if "--fill" in cmd:
        haystacks.append(commit_log_text)
    blob = "\n".join(h for h in haystacks if h)
    if issue.search(blob):
        return "ok", ""
    return "block", (f"PR description must reference an issue id matching /{pattern}/. "
                     "A PR may span several — list each with what it covers. "
                     "Pass it via --body (or --body-file).")


def main(data):
    cmd = fx.command(data)
    if not _is_pr_create(cmd):
        return
    pattern = fx.issue_pattern()
    if not pattern:
        return
    body_file_text = ""
    bf = _arg(cmd, "--body-file") or _arg(cmd, "-F")
    if bf:
        try:
            with open(bf, "r", errors="ignore") as f:
                body_file_text = f.read()
        except Exception:
            body_file_text = ""
    commit_log = ""
    if "--fill" in cmd:
        root = fx.repo_root() or "."
        base = fx.merge_base(root)
        rng = f"{base}..HEAD" if base else "HEAD"
        commit_log = fx.git_out(root, "log", "--pretty=format:%s%n%b", rng)
    verdict, reason = check(cmd, pattern, body_file_text, commit_log)
    if verdict == "block":
        fx.emit_block("check-pr-create: " + reason)


def _selftest() -> int:
    fails = 0
    P = r"(ENG|LGX|PROD)-\d+"

    def case(name, cmd, expect, pattern=P, bf="", cl=""):
        nonlocal fails
        got, _ = check(cmd, pattern, bf, cl)
        ok = got == expect
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {got} (want {expect})")

    case("body with id ok", 'gh pr create --title "x" --body "Closes ENG-3274"', "ok")
    case("title with id ok", 'gh pr create --title "feat ENG-3275" --body "x"', "ok")
    case("no id blocked", 'gh pr create --title "x" --body "some work"', "block")
    case("body-file with id ok", 'gh pr create --body-file pr.md', "ok", bf="Refs LGX-12")
    case("body-file without id blocked", 'gh pr create --body-file pr.md', "block", bf="just text")
    case("fill with id in commits ok", 'gh pr create --fill', "ok", cl="feat(api): x (ENG-3300)")
    case("non-create skipped", "gh pr view 3", "ok")
    case("gh -R o/r pr create no id blocked", 'gh -R o/r pr create --title "x" --body "work"', "block")
    case("gate OFF (empty pattern) -> ok even with no id", 'gh pr create --body "no id"', "ok", "")

    print(f"\ncheck-pr-create.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    fx.run(main)
