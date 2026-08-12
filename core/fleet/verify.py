#!/usr/bin/env python3
"""
verify — prove the factory's output actually WORKS, not just that it reads right.

The verification ladder (each rung lets you step further out of the loop):
  V0  typecheck/lint pass            "syntactically valid"
  V1  existing tests pass            "didn't break what worked"
  V2  fails-before / passes-after    "the change does what was asked"   <- the keystone rung

V0/V1 run the active pack's check.yaml commands in the WORKING repo. V2 proves a new test
actually exercises the change: run it against the BASE state (a throwaway git worktree at base
ref) — it must FAIL — then against the change — it must PASS. Only fail->pass counts (kills the
vacuous-test trap). On V2 pass, stamp the ledger so the completeness gate can require it.

Pure logic (check.yaml parsing, rung decision, skip detection) is isolated for --selftest; the
git/test execution runs only via main() against a real repo (dogfood, like eval-reviewers).

Run:  factory verify [--test <path>]        (run from the repo you're verifying)
      python3 core/fleet/verify.py --selftest
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

TEST_NAME_RE = re.compile(r"test|spec", re.I)


# --------------------------------------------------------------------------- #
# Pure: parse check.yaml  (commands + optional test_one with a {file} slot)
# --------------------------------------------------------------------------- #
def parse_check_text(text: str) -> dict:
    commands, cur_name, test_one, exercise = [], None, None, None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^test_one:\s*(.+)$", line.strip())
        if m:
            test_one = m.group(1).strip().strip("\"'")
            continue
        m = re.match(r"^exercise:\s*(.+)$", line.strip())
        if m:
            exercise = m.group(1).strip().strip("\"'")
            continue
        m = re.match(r"^-\s*name:\s*(.+)$", line.strip())
        if m:
            cur_name = m.group(1).strip().strip("\"'")
            continue
        m = re.match(r"^run:\s*(.+)$", line.strip())
        if m:
            commands.append((cur_name or f"cmd{len(commands)}", m.group(1).strip().strip("\"'")))
            cur_name = None
    v0 = [(n, c) for n, c in commands if not TEST_NAME_RE.search(n)]
    test = next((c for n, c in commands if TEST_NAME_RE.search(n)), None)
    return {"v0": v0, "test": test, "test_one": test_one, "exercise": exercise}


def load_check(pack: str, root: str | None = None) -> dict:
    path = os.path.join(fx.pack_dir(pack, root), "check.yaml")
    try:
        with open(path, "r", errors="ignore") as f:
            return parse_check_text(f.read())
    except Exception:
        return {"v0": [], "test": None, "test_one": None}


# --------------------------------------------------------------------------- #
# Pure: decide the rung reached from results
# --------------------------------------------------------------------------- #
def decide_rung(v0: str, v1: str, transition: str) -> dict:
    """v0/v1 in {pass,fail,skip,none}; transition in {pass,fail,inconclusive,none}.
    Returns {rung, ok, note}. A hard fail (v0/v1 == fail, or transition == fail) blocks."""
    if v0 == "fail":
        return {"rung": "FAIL", "ok": False, "note": "typecheck/lint failed"}
    if v1 == "fail":
        return {"rung": "FAIL", "ok": False, "note": "existing tests failed (regression)"}
    if transition == "fail":
        return {"rung": "V1", "ok": False, "note": "new test did NOT fail-before/pass-after (vacuous or wrong)"}
    if transition == "pass":
        return {"rung": "V2", "ok": True, "note": "fail-before/pass-after proven"}
    # no transition attempted
    if v1 == "pass":
        return {"rung": "V1", "ok": True, "note": "suite green; no change-proving test (consider --test)"}
    if v0 == "pass":
        return {"rung": "V0", "ok": True, "note": "typecheck/lint only; no tests ran"}
    return {"rung": "V-", "ok": False, "note": "nothing verified (no checks ran / all skipped)"}


# --------------------------------------------------------------------------- #
# Execution (real repo only; not in --selftest)
# --------------------------------------------------------------------------- #
def _run(cmd: str, cwd: str) -> str:
    """Return 'pass'|'fail'|'skip' (skip = the tool isn't installed here)."""
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=600)
    except Exception:
        return "skip"
    if p.returncode == 0:
        return "pass"
    blob = (p.stderr + p.stdout).lower()
    if p.returncode == 127 or "command not found" in blob or "not recognized" in blob:
        return "skip"
    return "fail"


def _exists_at_ref(root: str, ref: str, path: str) -> bool:
    return subprocess.run(["git", "-C", root, "cat-file", "-e", f"{ref}:{path}"],
                          capture_output=True).returncode == 0


def _at_base_state(root: str, files, base: str, fn):
    """Snapshot `files`, set them to their base content, call fn(), then restore the exact prior
    content and reset the index. Used to run any check/test against the pre-change state, in the
    working dir (deps present). Restores in a finally so a failure can't leave the tree reverted."""
    snap = {}
    for f in files:
        p = os.path.join(root, f)
        try:
            snap[f] = open(p, "rb").read() if os.path.exists(p) else None
        except Exception:
            snap[f] = None
    try:
        for f in files:
            p = os.path.join(root, f)
            if _exists_at_ref(root, base, f):
                subprocess.run(["git", "-C", root, "checkout", base, "--", f],
                               capture_output=True, timeout=30)
            elif os.path.exists(p):
                os.remove(p)  # new file -> didn't exist at base
        return fn()
    finally:
        for f, content in snap.items():
            p = os.path.join(root, f)
            if content is None:
                if os.path.exists(p):
                    os.remove(p)
            else:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "wb") as fh:
                    fh.write(content)
        subprocess.run(["git", "-C", root, "reset", "-q", "--", *files], capture_output=True, timeout=30)


def _accumulate(statuses) -> str:
    """Collapse per-command statuses into one. preexisting/pass are non-blocking; fail blocks."""
    if "fail" in statuses:
        return "fail"
    if any(s in ("pass", "preexisting") for s in statuses):
        return "pass"
    if "skip" in statuses:
        return "skip"
    return "none"


def differential(cmd: str, root: str, base: str, files, log, label: str) -> str:
    """Run `cmd`; if it FAILS, re-run it at base state. A failure that also fails at base is
    PRE-EXISTING debt (not blamed on this change); a failure that passed at base is a regression.
    Lazy: only reverts/re-runs on a failure, so the common (passing) path is one run."""
    after = _run(cmd, root)
    if after != "fail":
        log(f"  {label} -> {after}")
        return after
    if not base or not files:
        log(f"  {label} -> fail (no base to attribute against)")
        return "fail"
    before = _at_base_state(root, files, base, lambda: _run(cmd, root))
    if before == "fail":
        log(f"  {label} -> pre-existing (fails at base too; not this change's fault)")
        return "preexisting"
    log(f"  {label} -> fail (regression — passed at base, fails with the change)")
    return "fail"


def run_checks(root: str, chk: dict, base: str, files, log) -> tuple:
    """V0 commands + V1 test, each differential (pre-existing failures don't block).
    Returns (v0, v1, rows) where rows = [(label, status)] for the evidence table."""
    rows, v0s = [], []
    for name, cmd in chk["v0"]:
        r = differential(cmd, root, base, files, log, f"V0 {name}")
        v0s.append(r)
        rows.append((f"V0 {name}", r))
    v0 = _accumulate(v0s)
    v1 = "none"
    if chk["test"]:
        r = differential(chk["test"], root, base, files, log, "V1 existing tests")
        rows.append(("V1 existing tests", r))
        v1 = "pass" if r == "preexisting" else r
    return v0, v1, rows


def run_exercise(root: str, chk: dict, log) -> str | None:
    """V3: run the pack's optional `exercise` command (smoke the real path) and capture output.
    Returns the captured output, or None if no exercise declared / it couldn't run."""
    cmd = chk.get("exercise")
    if not cmd:
        return None
    try:
        p = subprocess.run(cmd, cwd=root, shell=True, capture_output=True, text=True, timeout=300)
    except Exception:
        log("  V3 exercise     -> skip (could not run)")
        return None
    out = (p.stdout + p.stderr).strip()
    log(f"  V3 exercise     -> {'ran' if p.returncode == 0 else 'ran (nonzero exit)'}")
    return out[:1500] if out else None


def evidence_md(pack: str, verdict: dict, rows, transition: str, test_file, exercise_out) -> str:
    """Build the PR-ready verify evidence block."""
    lines = [f"## Verify — rung {verdict['rung']} ({'OK' if verdict['ok'] else 'BLOCK'})",
             "", f"_{verdict['note']}_", "", "| check | result |", "|---|---|"]
    for label, status in rows:
        lines.append(f"| {label} | {status} |")
    if transition != "none":
        lines.append(f"| change-proving test | {transition} |")
    if test_file and transition == "pass":
        lines += ["", f"**Proof:** `{test_file}` fails on base, passes with the change "
                  "(fail-before/pass-after — non-vacuous)."]
    if exercise_out:
        lines += ["", "**Exercise (real path):**", "```", exercise_out, "```"]
    return "\n".join(lines)


def prove_transition(root: str, test_file: str, chk: dict, base: str, log) -> str:
    """fail-before/pass-after. Reverts only the IMPLEMENTATION files (changed-vs-base except the
    test) to base, runs the new test (must fail), restores. Returns 'pass'|'fail'|'inconclusive'."""
    if not base:
        log("  V2 transition   -> inconclusive (no base ref to compare against)")
        return "inconclusive"
    # check.yaml templates are pack-author config (npm-script trust); the {file} path comes from
    # --test, so shell-quote it to neutralize metacharacters before interpolation.
    cmd = (chk["test_one"] or chk["test"] or "").replace("{file}", shlex.quote(test_file))
    if not cmd:
        log("  V2 transition   -> inconclusive (pack declares no test command)")
        return "inconclusive"
    after = _run(cmd, root)  # current state = the change
    if after == "skip":
        log("  V2 transition   -> inconclusive (test tooling not installed here)")
        return "inconclusive"
    impl = sorted(f for f in fx.branch_touched_files(root) if f != test_file)
    if not impl:
        log("  V2 transition   -> inconclusive (no implementation files changed besides the test)")
        return "inconclusive"
    before = _at_base_state(root, impl, base, lambda: _run(cmd, root))
    log(f"  V2 transition   -> after={after} before={before}")
    return "pass" if (after == "pass" and before == "fail") else "fail"


def main(argv) -> int:
    root = fx.repo_root() or os.getcwd()
    packs = fx.active_packs(root)
    pack = packs[0] if packs else None
    if not pack:
        print("verify: no active pack (run `factory init` or add factory.config.yaml)", file=sys.stderr)
        return 2
    chk = load_check(pack, root)
    test_file = None
    if "--test" in argv:
        i = argv.index("--test")
        test_file = argv[i + 1] if i + 1 < len(argv) else None

    print(f"verify ({pack}):")
    log = print
    base = fx.base_ref(root)
    files = sorted(fx.branch_touched_files(root))
    v0, v1, rows = run_checks(root, chk, base, files, log)
    transition = prove_transition(root, test_file, chk, base, log) if test_file else "none"
    exercise_out = run_exercise(root, chk, log) if verdict_ok(v0, v1, transition) else None
    verdict = decide_rung(v0, v1, transition)
    print(f"\n  => rung {verdict['rung']}  ({'OK' if verdict['ok'] else 'BLOCK'}) — {verdict['note']}")

    # V4: write the PR-ready evidence block (durable + printed for the drive to lift into the PR)
    evidence = evidence_md(pack, verdict, rows, transition, test_file, exercise_out)
    try:
        out = os.path.join(root, ".claude", "state", "verify-evidence.md")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w") as f:
            f.write(evidence + "\n")
        print(f"\n  (evidence -> {os.path.relpath(out, root)})")
    except Exception:
        pass

    if verdict["ok"] and verdict["rung"] in ("V1", "V2"):
        # stamp the ledger so the completeness gate can require it
        try:
            import importlib.util
            sp = importlib.util.spec_from_file_location(
                "stamp_ledger", os.path.join(fx.FACTORY_HOME, "core", "hooks", "stamp-ledger.py"))
            sl = importlib.util.module_from_spec(sp); sp.loader.exec_module(sl)
            sl.stamp(root, "verify", "pass", f"rung {verdict['rung']}: {verdict['note']}")
            print("  (stamped ledger: verify=pass)")
        except Exception:
            pass
    return 0 if verdict["ok"] else 1


def verdict_ok(v0: str, v1: str, transition: str) -> bool:
    """Whether to bother running the (heavier) V3 exercise — only if the change is otherwise sound."""
    return decide_rung(v0, v1, transition)["ok"]


def _selftest() -> int:
    fails = 0

    def ok(cond, msg):
        nonlocal fails
        if not cond:
            fails += 1
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")

    # parser
    p = parse_check_text(
        "commands:\n  - name: typecheck\n    run: pnpm tsc --noEmit\n  - name: test\n    run: pnpm test\ntest_one: pnpm vitest run {file}\n")
    ok(p["test"] == "pnpm test", f"parses test command (got {p['test']})")
    ok(p["test_one"] == "pnpm vitest run {file}", f"parses test_one (got {p['test_one']})")
    ok(len(p["v0"]) == 1 and p["v0"][0][0] == "typecheck", f"V0 = non-test commands (got {p['v0']})")

    # rung decisions
    ok(decide_rung("pass", "pass", "pass")["rung"] == "V2", "fail-before/pass-after -> V2")
    ok(decide_rung("pass", "pass", "pass")["ok"], "V2 is ok")
    ok(decide_rung("pass", "pass", "none")["rung"] == "V1", "suite green, no test -> V1")
    ok(decide_rung("pass", "none", "none")["rung"] == "V0", "lint only -> V0")
    ok(decide_rung("fail", "pass", "none")["rung"] == "FAIL", "lint fail -> FAIL")
    ok(not decide_rung("fail", "pass", "none")["ok"], "FAIL is not ok")
    ok(decide_rung("pass", "fail", "none")["rung"] == "FAIL", "test regression -> FAIL")
    ok(decide_rung("pass", "pass", "fail")["rung"] == "V1" and not decide_rung("pass", "pass", "fail")["ok"],
       "vacuous/wrong new test -> V1 + BLOCK")
    ok(decide_rung("skip", "skip", "none")["rung"] == "V-", "all skipped -> V- (nothing verified)")

    # differential accumulation: pre-existing failures don't block
    ok(_accumulate(["pass", "preexisting"]) == "pass", "preexisting is non-blocking")
    ok(_accumulate(["pass", "fail"]) == "fail", "a real fail blocks")
    ok(_accumulate(["skip", "skip"]) == "skip", "all skip -> skip")
    ok(_accumulate(["preexisting"]) == "pass", "lone preexisting -> pass (not blamed on change)")

    # evidence block (V4)
    md = evidence_md("ts-next", {"rung": "V2", "ok": True, "note": "proven"},
                     [("V0 typecheck", "pass"), ("V1 existing tests", "pass")],
                     "pass", "src/x.test.ts", "HTTP 200 {ok:true}")
    ok("rung V2" in md and "| V0 typecheck | pass |" in md, "evidence has rung + check rows")
    ok("**Proof:**" in md and "src/x.test.ts" in md, "evidence cites the change-proving test")
    ok("Exercise (real path)" in md and "HTTP 200" in md, "evidence includes exercise output")

    print(f"\nverify.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else main(sys.argv[1:]))
