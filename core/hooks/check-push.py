#!/usr/bin/env python3
"""
check-push — push gate (PreToolUse: Bash on `git push`).

Block a direct push to a base branch; warn on a force-push. Base branches come from
config (`base_branches`, default main/staging). Pure logic in `check()`.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

FORCE_FLAGS = ("--force", "--force-with-lease", "-f")


def current_branch():
    try:
        return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def check(cmd: str, base, cur_branch: str = ""):
    """Return ('ok'|'block'|'warn', reason). Token-based so a feature branch that merely
    contains a base name as a substring isn't falsely blocked."""
    base = tuple(base)
    sub, args = fx.cli_subcommand(cmd, "git")
    if sub != "push":
        return "ok", ""
    positionals = [a for a in args if not a.startswith("-")]
    forced = any(f in args for f in FORCE_FLAGS)
    if len(positionals) >= 2:
        dest = positionals[-1].split(":")[-1]
        if dest.startswith("refs/heads/"):
            dest = dest[len("refs/heads/"):]
        if dest in base:
            return "block", f"direct push to base branch '{dest}' — base branches change only via PR"
    elif cur_branch in base:
        return "block", f"you are on '{cur_branch}' — don't push a base branch directly; use a feature branch + PR"
    if forced:
        return "warn", "force-push detected — make sure this is your feature branch, never a base branch"
    return "ok", ""


def cross_repo_only(cmd: str, project_dir: str) -> bool:
    """True when every git invocation in the command uses -C pointing outside project_dir —
    a push at another repo shouldn't be gated by THIS project's branch policy."""
    if not project_dir:
        return False
    if re.search(r"git\s+(?:--\S+\s+)*push\b", cmd):
        return False  # a bare `git push` (no -C) targets the project repo
    dirs = re.findall(r"git\s+-C\s+(\"[^\"]+\"|'[^']+'|\S+)", cmd)
    if not dirs:
        return False
    proj = os.path.realpath(os.path.expanduser(project_dir))
    for d in dirs:
        d = os.path.realpath(os.path.expanduser(d.strip("\"'")))
        if d == proj or d.startswith(proj + os.sep):
            return False
    return True


def main(data):
    if cross_repo_only(fx.command(data), os.environ.get("CLAUDE_PROJECT_DIR", "")):
        return
    verdict, reason = check(fx.command(data), fx.base_branches(), current_branch())
    if verdict == "block":
        fx.emit_block("check-push: " + reason + ".")
    elif verdict == "warn":
        fx.emit_warn("⚠️  check-push: " + reason)


def _selftest() -> int:
    fails = 0
    B = ["main", "staging"]

    def case(name, cmd, cur, expect):
        nonlocal fails
        got, _ = check(cmd, B, cur)
        ok = got == expect
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {got} (want {expect})")

    case("push origin main blocked", "git push origin main", "feat/x", "block")
    case("push HEAD:staging blocked", "git push origin HEAD:staging", "feat/x", "block")
    case("bare push on main blocked", "git push", "main", "block")
    case("push feature ok", "git push origin feat/core/git-safety", "feat/core/git-safety", "ok")
    case("force-push feature warns", "git push --force origin feat/x", "feat/x", "warn")
    case("force-push main blocked (target wins)", "git push --force origin main", "feat/x", "block")
    case("feature w/ 'main' substring ok", "git push origin feat/main-menu", "feat/main-menu", "ok")
    case("implicit push on main blocked", "git push origin", "main", "block")
    case("implicit push on feature ok", "git push origin", "feat/x", "ok")
    case("non-push skipped", "git status", "main", "ok")
    # global flags must not hide the push subcommand from the gate:
    case("git -C dir push main blocked", "git -C /repo push origin main", "feat/x", "block")
    case("git --no-pager push main blocked", "git --no-pager push origin main", "feat/x", "block")

    # cross_repo_only: another repo's push isn't gated by this project's policy
    def xcase(name, cmd, proj, expect):
        nonlocal fails
        got = cross_repo_only(cmd, proj)
        ok = got == expect
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {got} (want {expect})")

    xcase("-C other repo push skipped", "git -C /Users/x/Repos/other push -q", "/Users/x/Repos/proj", True)
    xcase("-C inside project still gated", "git -C /Users/x/Repos/proj/sub push", "/Users/x/Repos/proj", False)
    xcase("bare push still gated", "git -C /Users/x/Repos/other add .; git push", "/Users/x/Repos/proj", False)
    xcase("no -C still gated", "git push origin main", "/Users/x/Repos/proj", False)
    xcase("no project dir still gated", "git -C /Users/x/Repos/other push", "", False)

    print(f"\ncheck-push.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    fx.run(main)
