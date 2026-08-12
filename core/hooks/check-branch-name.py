#!/usr/bin/env python3
"""
check-branch-name — branch-name format gate (PreToolUse: Bash).

Block `git checkout -b` / `git switch -c` / `git branch <name>` when the new branch name
doesn't match the configured `type/scope/desc` format. Types + require_scope come from the
active pack's conventions.json. Pure logic in `check()`.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

DEFAULT_TYPES = fx.CORE_BRANCH_TYPES  # single source of truth (core); packs may override


def branch_from(cmd: str):
    """The name of a NEW branch being created, or None. Subcommand-based (global flags stripped)
    so `git -C dir checkout -b` is caught, while flag forms (`git branch -d topic`, `-m old new`,
    `-a`) are NOT treated as creates."""
    sub, args = fx.cli_subcommand(cmd, "git")
    if sub == "checkout" and len(args) >= 2 and args[0] == "-b":
        return args[1]
    if sub == "switch" and len(args) >= 2 and args[0] in ("-c", "--create"):
        return args[1]
    if sub == "branch" and len(args) == 1 and not args[0].startswith("-"):
        return args[0]
    return None


def check(cmd: str, types=None, require_scope=True):
    """Return ('ok'|'block'|'skip', branch, reason)."""
    types = types or DEFAULT_TYPES
    t = "(" + "|".join(types) + ")"
    if require_scope:
        valid = re.compile(rf"^{t}/[a-z0-9-]+/[a-z0-9._-]+$")
    else:
        valid = re.compile(rf"^{t}/[a-z0-9._-]+$")
    # hotfix may be a 2-segment `hotfix/TICKET-desc`
    valid_hotfix2 = re.compile(r"^hotfix/[A-Za-z0-9._-]+$") if "hotfix" in types else None

    name = branch_from(cmd)
    if name is None:
        return "skip", None, ""
    if valid.match(name) or (valid_hotfix2 and valid_hotfix2.match(name)):
        return "ok", name, ""
    shape = "type/scope/desc (scope required)" if require_scope else "type/desc"
    return ("block", name,
            f"branch '{name}' must be `{shape}`, e.g. feat/core/git-safety. types: {', '.join(types)}")


def main(data):
    conv = fx.pack_conventions().get("branch", {})
    types = conv.get("types") or DEFAULT_TYPES
    require_scope = conv.get("require_scope", True)
    verdict, _, reason = check(fx.command(data), types, require_scope)
    if verdict == "block":
        fx.emit_block("check-branch-name: " + reason)


def _selftest() -> int:
    fails = 0
    T = DEFAULT_TYPES

    def case(name, cmd, expect, types=T, scope=True):
        nonlocal fails
        got, _, _ = check(cmd, types, scope)
        ok = got == expect
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {got} (want {expect})")

    case("valid feat/core/x", "git checkout -b feat/core/git-safety", "ok")
    case("valid switch -c", "git switch -c fix/api/null-guard", "ok")
    case("valid git branch", "git branch chore/packs/add-flutter", "ok")
    case("valid hotfix 3-seg", "git checkout -b hotfix/api/revert", "ok")
    case("valid hotfix ticket", "git checkout -b hotfix/PROD-140-fix", "ok")
    case("missing scope blocked", "git checkout -b feat/git-safety", "block")
    case("no type blocked", "git checkout -b git-safety", "block")
    case("bad type blocked", "git checkout -b feature/core/x", "block")
    case("uppercase blocked", "git checkout -b feat/core/MyBranch", "block")
    case("require_scope=false allows 2-seg", "git checkout -b feat/my-thing", "ok", T, False)
    case("switch --create long-form validated", "git switch --create badname", "block")
    case("git -C dir checkout -b bad blocked", "git -C /repo checkout -b badname", "block")
    case("git -C dir checkout -b valid ok", "git -C /repo checkout -b feat/core/x", "ok")
    case("non-create skipped", "git status", "skip")
    case("git branch list skipped", "git branch -a", "skip")
    case("git branch -d delete skipped", "git branch -d badname", "skip")
    case("git branch -m rename skipped", "git branch -m old newname", "skip")
    case("git push skipped", "git push origin main", "skip")

    print(f"\ncheck-branch-name.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    fx.run(main)
