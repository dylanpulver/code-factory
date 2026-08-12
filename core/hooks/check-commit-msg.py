#!/usr/bin/env python3
"""
check-commit-msg — commit gate (PreToolUse: Bash on `git commit`).

Two checks:
1. The message is a single-line Conventional Commit (`type(scope): subject`, no trailing period).
   Types come from the active pack's conventions.json.
2. The STAGED diff carries no universal-unsafe content (secret / duplicate file) nor any
   stack-specific staged-block pattern from the pack (e.g. `as any`, `.only`).

Pure logic in `check_message()` / `scan_staged()` so `--selftest` needs no git.
"""
import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

DEFAULT_TYPES = fx.CORE_COMMIT_TYPES  # single source of truth (core); packs may override

# Universal staged-block patterns (language-agnostic) — secrets + iCloud dup files.
UNIVERSAL_STAGED = [
    (re.compile(r"(sk-ant-[A-Za-z0-9]|sk_live_|sk_test_|pk_live_|(AKIA|ASIA)[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)"),
     "a hardcoded secret/credential"),
]
DUP_FILE = re.compile(r" \d+\.\w+$")  # iCloud "name 2.ts" duplicates


def conventional(types):
    t = "(" + "|".join(types) + ")"
    return re.compile(rf"^{t}(\([a-z0-9.-]+\))?!?: \S.*$")


def msg_from(cmd: str):
    """Extract the commit message from -m / --message. None for editor/-F commits."""
    try:
        parts = shlex.split(cmd or "")
    except ValueError:
        return None
    msgs, i = [], 0
    while i < len(parts):
        tok = parts[i]
        if tok in ("-m", "--message"):
            if i + 1 >= len(parts):
                return None
            msgs.append(parts[i + 1]); i += 2; continue
        if tok.startswith("--message="):
            msgs.append(tok.split("=", 1)[1]); i += 1; continue
        if tok.startswith("-m") and len(tok) > 2:
            msgs.append(tok[2:]); i += 1; continue
        i += 1
    if not msgs:
        return None
    return "\n".join(msgs) if len(msgs) > 1 else msgs[0]


def check_message(msg, types=None):
    types = types or DEFAULT_TYPES
    if msg is None:
        return "skip", ""
    if "\n" in msg.strip():
        return "block", "commit message must be a single line"
    if msg.rstrip().endswith("."):
        return "block", "no trailing period in the commit subject"
    if not conventional(types).match(msg.strip()):
        return "block", f"message must be Conventional: `type(scope): subject` (types: {', '.join(types)})"
    return "ok", ""


def scan_staged(added_lines, names, patterns):
    """added_lines: added '+' lines (no +). names: staged paths. patterns: [(regex, label)]."""
    issues = []
    for n in names:
        if DUP_FILE.search(n.strip()):
            issues.append(f"staged a duplicate file '{n.strip()}' (iCloud ' 2' artifact) — remove it")
    for ln in added_lines:
        for rx, label in patterns:
            if rx.search(ln):
                issues.append(f"staged change adds {label}: {ln.strip()[:80]}")
    return issues


def _staged(root):
    diff = fx.staged_diff(root)
    added = [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    try:
        names = subprocess.run(["git", "-C", root, "diff", "--cached", "--name-only"],
                               capture_output=True, text=True, timeout=8).stdout.splitlines()
    except Exception:
        names = []
    return added, names


def _patterns():
    pats = list(UNIVERSAL_STAGED)
    for p in fx.pack_conventions().get("staged_block", []):
        try:
            pats.append((re.compile(p["regex"]), p["label"]))
        except (re.error, KeyError):
            continue
    return pats


def main(data):
    cmd = fx.command(data)
    sub, _ = fx.cli_subcommand(cmd, "git")
    if sub != "commit":  # subcommand-based so `git -C dir commit` / `git --no-pager commit` still gate
        return
    types = fx.pack_conventions().get("commit", {}).get("types") or DEFAULT_TYPES
    problems = []
    verdict, reason = check_message(msg_from(cmd), types)
    if verdict == "block":
        problems.append(reason)
    root = fx.repo_root()
    if root:
        added, names = _staged(root)
        problems += scan_staged(added, names, _patterns())
    if problems:
        fx.emit_block("check-commit-msg blocked this commit:\n- " + "\n- ".join(problems) +
                      "\nFix and recommit. (Genuine false positive? say so and proceed.)")


def _selftest() -> int:
    fails = 0
    T = DEFAULT_TYPES
    # a representative pattern set (universal + a couple stack patterns)
    PATS = list(UNIVERSAL_STAGED) + [
        (re.compile(r"\bas any\b"), "as any"),
        (re.compile(r"\.only\("), ".only("),
    ]

    def mcase(name, msg, expect):
        nonlocal fails
        got, _ = check_message(msg, T)
        ok = got == expect
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] msg: {name} -> {got} (want {expect})")

    def scase(name, lines, names, expect_some):
        nonlocal fails
        got = scan_staged(lines, names, PATS)
        ok = (len(got) > 0) == expect_some
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] staged: {name} -> {len(got)} (want {'some' if expect_some else 'none'})")

    mcase("conventional ok", "feat(core): add gate", "ok")
    mcase("scope all ok", "chore(all): bump deps", "ok")
    mcase("no scope ok", "docs: update readme", "ok")
    mcase("breaking ok", "feat(core)!: change protocol", "ok")
    mcase("wip blocked", "wip", "block")
    mcase("trailing period blocked", "feat(core): add gate.", "block")
    mcase("bad type blocked", "feature(core): x", "block")
    mcase("editor commit skipped", None, "skip")

    def fcase(name, cmd, expect):
        nonlocal fails
        got, _ = check_message(msg_from(cmd), T)
        ok = got == expect
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] extract: {name} -> {got} (want {expect})")

    fcase("-m conventional ok", 'git commit -m "feat(core): x"', "ok")
    fcase("--message form validated", 'git commit --message "wip"', "block")
    fcase("--message= form validated", 'git commit --message="wip"', "block")
    fcase("-mGLUED form validated", 'git commit -m"wip"', "block")
    fcase("repeated -m (multiline) blocked", 'git commit -m "feat(core): x" -m "body"', "block")
    fcase("editor commit (no -m) skipped", "git commit", "skip")

    scase("clean staged", ["const x = foo()"], ["core/x.ts"], False)
    scase("as any staged", ["const y = z as any"], ["core/x.ts"], True)
    scase("secret staged", ['const k = "sk-ant-api03-XX"'], ["core/x.ts"], True)
    scase(".only staged", ["it.only('x', () => {})"], ["x.test.ts"], True)
    scase("dup ' 2' file staged", ["ok line"], ["x/Surface 2.tsx"], True)

    print(f"\ncheck-commit-msg.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    fx.run(main)
