#!/usr/bin/env python3
"""
eval-reviewers — the real-catch regression ratchet (deterministic guard).

Validates each pack's reviewer regression set (reviewers/regression.json): every case is
well-formed and names a real reviewer. Reports coverage (which reviewers have real-catch cases).
This is the part that runs free in the selftest suite, so the ratchet can't silently rot.

The BEHAVIORAL half — actually spawning each reviewer (LLM) against the held-out cases and
checking it flags the bugs / passes the fixes — is run on demand via the /eval-reviewers command
(it costs tokens and is non-deterministic, so it's not in the suite).

Run:  factory eval-reviewers          (coverage + case report)
      python3 core/fleet/eval-reviewers.py --selftest   (structural gate)
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

VALID_EXPECT = ("flag", "clean")
TREND = os.path.join(".claude", "state", "eval-trend.jsonl")


def packs_with_regression():
    base = os.path.join(fx.FACTORY_HOME, "packs")
    out = []
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        if os.path.isfile(os.path.join(d, "reviewers", "regression.json")):
            out.append(os.path.basename(d))
    return out


def reviewer_keys(pack):
    rdir = os.path.join(fx.pack_dir(pack), "reviewers")
    return {os.path.basename(f).replace("-reviewer.md", "").replace(".md", "")
            for f in glob.glob(os.path.join(rdir, "*.md"))
            if os.path.basename(f).lower() != "readme.md"}


def validate_pack(pack, ok):
    path = os.path.join(fx.pack_dir(pack), "reviewers", "regression.json")
    try:
        cases = json.load(open(path)).get("cases", [])
    except Exception as e:
        ok(False, f"[{pack}] regression.json loads ({e})")
        return {}
    keys = reviewer_keys(pack)
    cov = {}  # reviewer -> [flag, clean]
    for i, c in enumerate(cases):
        tag = c.get("name", f"#{i}")
        rev, expect, code = c.get("reviewer"), c.get("expect"), c.get("code", "")
        ok(rev in keys, f"[{pack}] case '{tag}': reviewer '{rev}' has a file")
        ok(expect in VALID_EXPECT, f"[{pack}] case '{tag}': expect is flag|clean (got {expect})")
        ok(bool(code.strip()), f"[{pack}] case '{tag}': has code")
        if expect == "flag":
            ok(bool(c.get("must_flag")), f"[{pack}] case '{tag}': flag case states must_flag")
        if rev:
            cov.setdefault(rev, [0, 0])
            cov[rev][0 if expect == "flag" else 1] += 1
    return cov


def report():
    fails = []

    def ok(cond, msg):
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    packs = packs_with_regression()
    if not packs:
        print("  [PASS] no regression sets yet (nothing to guard)")
        return 0
    for pack in packs:
        print(f"\n=== regression set: {pack} ===")
        cov = validate_pack(pack, ok)
        print(f"  -- coverage ({pack}) --")
        routed = set()
        try:
            m = json.load(open(os.path.join(fx.pack_dir(pack), "reviewers", "dispatch-matrix.json")))
            routed |= set(m.get("always", []))
            for s in m.get("surfaces", {}).values():
                routed |= set(s.get("reviewers", []))
        except Exception:
            pass
        for rev in sorted(routed):
            f, c = cov.get(rev, [0, 0])
            mark = "•" if f else "—"
            print(f"     {mark} {rev:22} flag={f} clean={c}" + ("   (no real-catch case yet)" if not f else ""))
    return len(fails)


def all_cases():
    """Every regression case across packs (each flag case = a planted bug, each clean = its fix)."""
    out = []
    for pack in packs_with_regression():
        try:
            cases = json.load(open(os.path.join(fx.pack_dir(pack), "reviewers", "regression.json"))).get("cases", [])
        except Exception:
            continue
        out += [{**c, "pack": pack} for c in cases]
    return out


def score_run(cases, verdicts):
    """The empirical loop's core: turn a behavioral run into the TWO numbers that matter (per the
    literature — recall alone measures the wrong half; FP/noise is the adoption-killer).
      catch_rate = recall on planted bugs (flag cases the reviewer correctly flagged)
      fp_rate    = false alarms on known-good code (clean cases the reviewer wrongly flagged)
    verdicts: {case_name: 'flag'|'clean'} — what the reviewer actually said. Ground truth is
    objective (we planted the bug), so no judge is needed. Missing verdicts are 'unrun'.
    Returns (by_reviewer, unrun_case_names)."""
    by_rev, unrun = {}, []
    for c in cases:
        rev, name, expect = c.get("reviewer"), c.get("name"), c.get("expect")
        if not rev or expect not in VALID_EXPECT:
            continue
        r = by_rev.setdefault(rev, {"catch": 0, "n_flag": 0, "fp": 0, "n_clean": 0})
        if name not in verdicts:
            unrun.append(name)
            continue
        said = verdicts[name]
        if expect == "flag":
            r["n_flag"] += 1
            r["catch"] += 1 if said == "flag" else 0
        else:  # clean — reviewer should stay quiet
            r["n_clean"] += 1
            r["fp"] += 1 if said == "flag" else 0
    for r in by_rev.values():
        r["catch_rate"] = (r["catch"] / r["n_flag"]) if r["n_flag"] else None
        r["fp_rate"] = (r["fp"] / r["n_clean"]) if r["n_clean"] else None
    return by_rev, unrun


def print_scoreboard(by_rev, unrun):
    def pct(x):
        return " n/a" if x is None else f"{x * 100:3.0f}%"
    print("\n  reviewer                catch-rate    FP-rate     verdict")
    print("  " + "-" * 64)
    for rev in sorted(by_rev):
        r = by_rev[rev]
        cr, fp = r["catch_rate"], r["fp_rate"]
        if cr is None:
            note = "no flag case"
        elif fp is None:
            note = "no clean case — FP UNMEASURED (blind spot)"
        elif cr >= 0.7 and fp <= 0.2:
            note = "net-positive"
        elif fp > cr:
            note = "noisier than useful — prune or tier down"
        else:
            note = "marginal — sharpen prompt, re-measure"
        print(f"  {rev:22}  {pct(cr)} ({r['catch']}/{r['n_flag']})   {pct(fp)} ({r['fp']}/{r['n_clean']})   {note}")
    if unrun:
        print(f"\n  {len(unrun)} case(s) unrun (no verdict): {', '.join(unrun[:8])}" + (" …" if len(unrun) > 8 else ""))
    print("\n  Verdicts come from the on-demand behavioral run: /eval-reviewers spawns each reviewer on its")
    print("  cases, records flag|clean per case to a verdicts JSON, then: eval-reviewers.py --score <that>.")


# --------------------------------------------------------------------------- #
# Phase 2: change-detection + trend recording + regression alerting
# The seeded eval is objective (planted bugs), so it's the prune-decision instrument. It should
# fire exactly when a reviewer prompt changes (that's when catch-rate could regress) — so nobody
# has to remember. Given the literature's run-to-run instability, we RECORD + ALERT, never gate.
# --------------------------------------------------------------------------- #
def reviewer_files():
    """Every reviewer prompt + regression.json across packs (the eval's inputs)."""
    out = []
    for rdir in sorted(glob.glob(os.path.join(fx.FACTORY_HOME, "packs", "*", "reviewers"))):
        out += sorted(f for f in glob.glob(os.path.join(rdir, "*.md"))
                      if os.path.basename(f).lower() != "readme.md")
        rj = os.path.join(rdir, "regression.json")
        if os.path.exists(rj):
            out.append(rj)
    return out


def reviewer_files_hash():
    """Content hash of the eval inputs — freshness key for a trend row."""
    h = hashlib.sha1()
    for f in reviewer_files():
        try:
            h.update(open(f, "rb").read())
        except Exception:
            pass
    return h.hexdigest()[:12]


def reviewer_files_changed(root):
    """Which reviewer prompts / regression sets this branch touched — the auto-eval trigger."""
    return sorted(f for f in fx.branch_touched_files(root)
                  if re.search(r"/reviewers/.*\.md$", "/" + f) or f.endswith("regression.json"))


def _scoreboard_map(by_rev):
    return {rev: {"catch_rate": r["catch_rate"], "fp_rate": r["fp_rate"]} for rev, r in by_rev.items()}


def append_trend(root, by_rev, files_hash, ts):
    row = {"ts": ts, "reviewer_files_hash": files_hash, "scoreboard": _scoreboard_map(by_rev)}
    out = os.path.join(root, TREND)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def last_trend(root):
    try:
        lines = [l for l in open(os.path.join(root, TREND)).read().splitlines() if l.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:
        return None


def regression_alerts(prev, cur, cr_drop=0.15, fp_rise=0.15):
    """prev/cur = scoreboard maps {rev:{catch_rate,fp_rate}} (prev may be a full trend row). Alert
    when a reviewer's catch-rate dropped or FP-rate rose beyond threshold — the thresholds absorb
    the known run-to-run wobble so only real regressions surface."""
    if not prev:
        return []
    p = prev.get("scoreboard", prev) if isinstance(prev, dict) else {}
    alerts = []
    for rev, c in cur.items():
        pr = p.get(rev)
        if not pr:
            continue
        c0, c1 = pr.get("catch_rate"), c.get("catch_rate")
        f0, f1 = pr.get("fp_rate"), c.get("fp_rate")
        if c0 is not None and c1 is not None and (c0 - c1) > cr_drop:
            alerts.append(f"{rev}: catch-rate dropped {c0 * 100:.0f}%->{c1 * 100:.0f}% (>{cr_drop * 100:.0f}pp)")
        if f0 is not None and f1 is not None and (f1 - f0) > fp_rise:
            alerts.append(f"{rev}: FP-rate rose {f0 * 100:.0f}%->{f1 * 100:.0f}% (>{fp_rise * 100:.0f}pp)")
    return alerts


def _selftest() -> int:
    fails = report()

    # scoring core (synthetic — proves the two numbers are computed right)
    cases = [{"reviewer": "r", "name": "bug1", "expect": "flag"},
             {"reviewer": "r", "name": "bug2", "expect": "flag"},
             {"reviewer": "r", "name": "ok1", "expect": "clean"},
             {"reviewer": "r", "name": "ok2", "expect": "clean"}]
    by_rev, unrun = score_run(cases, {"bug1": "flag", "bug2": "clean", "ok1": "clean", "ok2": "flag"})
    r = by_rev["r"]
    _, unrun2 = score_run(cases, {"bug1": "flag"})
    by2, _ = score_run([{"reviewer": "x", "name": "b", "expect": "flag"}], {"b": "flag"})
    checks = [
        ("catch_rate = caught/planted (1/2)", r["catch_rate"] == 0.5),
        ("fp_rate = false-alarms/clean (1/2)", r["fp_rate"] == 0.5),
        ("all verdicts present -> no unrun", unrun == []),
        ("missing verdicts -> unrun", set(unrun2) == {"bug2", "ok1", "ok2"}),
        ("no clean case -> fp_rate None (blind spot)", by2["x"]["fp_rate"] is None),
    ]
    for name, cond in checks:
        print(f"  [{'PASS' if cond else 'FAIL'}] score: {name}")
        if not cond:
            fails += 1

    # regression alerts (pure — thresholds absorb wobble, only real drops fire)
    prev = {"scoreboard": {"security": {"catch_rate": 1.0, "fp_rate": 0.0},
                           "data-access": {"catch_rate": 0.8, "fp_rate": 0.1}}}
    cur = {"security": {"catch_rate": 1.0, "fp_rate": 0.0},
           "data-access": {"catch_rate": 0.5, "fp_rate": 0.4}}
    al = regression_alerts(prev, cur)
    rchecks = [
        ("catch-drop alert fires for data-access", any(a.startswith("data-access") and "catch-rate dropped" in a for a in al)),
        ("fp-rise alert fires", any("FP-rate rose" in a for a in al)),
        ("stable reviewer -> no alert", not any(a.startswith("security") for a in al)),
        ("no prev -> no alerts", regression_alerts(None, cur) == []),
        ("wobble within threshold -> no alert",
         regression_alerts({"data-access": {"catch_rate": 0.8, "fp_rate": 0.1}},
                           {"data-access": {"catch_rate": 0.7, "fp_rate": 0.15}}) == []),
    ]
    for name, cond in rchecks:
        print(f"  [{'PASS' if cond else 'FAIL'}] trend: {name}")
        if not cond:
            fails += 1

    print(f"\neval-reviewers.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--changed" in sys.argv:
        # the auto-eval trigger: did this branch touch a reviewer prompt / regression set?
        ch = reviewer_files_changed(fx.repo_root() or ".")
        if ch:
            print("reviewer prompt / regression changed on this branch — re-run the seeded eval:")
            for f in ch:
                print(f"  {f}")
        else:
            print("no reviewer-prompt / regression change on this branch")
        sys.exit(0)
    if "--score" in sys.argv:
        i = sys.argv.index("--score")
        vpath = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        verdicts = {}
        if vpath and os.path.exists(vpath):
            try:
                verdicts = json.load(open(vpath))
            except Exception as e:
                print(f"could not read verdicts {vpath}: {e}", file=sys.stderr)
        elif vpath:
            print(f"verdicts file not found: {vpath} — printing an empty scoreboard (all unrun)", file=sys.stderr)
        by_rev, unrun = score_run(all_cases(), verdicts)
        print_scoreboard(by_rev, unrun)
        if "--record" in sys.argv:
            root = fx.repo_root() or "."
            prev = last_trend(root)
            alerts = regression_alerts(prev, _scoreboard_map(by_rev))
            append_trend(root, by_rev, reviewer_files_hash(), datetime.now().isoformat(timespec="seconds"))
            if alerts:
                print("\n  ⚠ REGRESSION vs last recorded eval:")
                for a in alerts:
                    print(f"    - {a}")
            else:
                print("\n  no regression vs last recorded eval (this run recorded to the trend).")
        sys.exit(0)
    sys.exit(0 if report() == 0 else 1)
