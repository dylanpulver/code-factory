#!/usr/bin/env python3
"""
review-rollup — the learning-loop: synthesize the empirical loop into a per-reviewer verdict.

Reads the two data sources the loop produces and prints a per-reviewer worklist:
  - .claude/state/eval-trend.jsonl  OBJECTIVE — seeded catch-rate + FP-rate (planted bugs, no judge).
                                    From eval-reviewers.py --score --record. Drives the prune call.
  - .claude/state/review-log.jsonl  DIRECTIONAL — real-run fire-rate / resolution / dismiss.
                                    From log-review.py on every /ship-it. Flags drift.

The objective numbers decide keep/prune (the research is clear: a reviewer whose FP-rate beats its
catch-rate is net-negative — and a fleet of them can underperform one good reviewer). The real-world
numbers add tier-down / drift signal. Like research-factory's learning-loop, this NEVER auto-changes
anything — it's a review worklist. You prune/tier/sharpen by hand.

Usage: factory review-rollup   |   python3 core/fleet/review-rollup.py --selftest
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

TREND = os.path.join(".claude", "state", "eval-trend.jsonl")
LOG = os.path.join(".claude", "state", "review-log.jsonl")


def _read_jsonl(path):
    out = []
    try:
        for line in open(path):
            line = line.strip()
            if line:
                out.append(json.loads(line))
    except Exception:
        pass
    return out


def _verdict(cr, fp, resolution, dismiss, ran, fires):
    """Objective (seeded) first — that's what the prune decision rests on; real-world as fallback."""
    if cr is not None and fp is not None:
        if fp > cr:
            return "PRUNE — seeded FP-rate exceeds catch-rate (noisier than useful)"
        if cr >= 0.7 and fp <= 0.2:
            if ran >= 10 and fires <= max(1, ran // 10):
                return "KEEP — but TIER-DOWN candidate (net-positive yet rarely fires on real diffs)"
            return "KEEP — net-positive (seeded)"
        if cr < 0.5:
            return "SHARPEN — low seeded catch-rate (tighten the bug-class checklist, re-measure)"
        return "MONITOR — marginal seeded numbers"
    # no objective numbers yet -> lean on real-world drift
    if dismiss is not None and dismiss > 0.5:
        return "SHARPEN? — dismissed on >half of real fires (noisy); run the seeded eval to confirm"
    if resolution is not None and resolution >= 0.5:
        return "KEEP? — often acted on in real use (no seeded eval recorded yet)"
    return "NO DATA — run the seeded eval: eval-reviewers.py --score <verdicts> --record"


def rollup(trend_rows, log_rows):
    """Per-reviewer synthesis: objective (latest trend row) + aggregated real-world (all log rows)."""
    latest = trend_rows[-1].get("scoreboard", {}) if trend_rows else {}
    real = {}
    for r in log_rows:
        rev = r.get("reviewer")
        if not rev:
            continue
        d = real.setdefault(rev, {"ran": 0, "fires": 0, "fixed": 0, "dismissed": 0})
        d["ran"] += 1
        if r.get("fired"):
            d["fires"] += 1
            o = r.get("outcome")
            if o == "fixed":
                d["fixed"] += 1
            elif o == "dismissed":
                d["dismissed"] += 1
    out = {}
    for rev in sorted(set(latest) | set(real)):
        obj = latest.get(rev, {})
        cr, fp = obj.get("catch_rate"), obj.get("fp_rate")
        d = real.get(rev, {"ran": 0, "fires": 0, "fixed": 0, "dismissed": 0})
        resolution = (d["fixed"] / d["fires"]) if d["fires"] else None
        dismiss = (d["dismissed"] / d["fires"]) if d["fires"] else None
        out[rev] = {
            "catch_rate": cr, "fp_rate": fp,
            "ran": d["ran"], "fires": d["fires"],
            "resolution_rate": resolution, "dismiss_rate": dismiss,
            "verdict": _verdict(cr, fp, resolution, dismiss, d["ran"], d["fires"]),
        }
    return out


def print_table(by_rev):
    def pct(x):
        return "  -" if x is None else f"{x * 100:3.0f}%"
    if not by_rev:
        print("  no data yet — ship a change (fills the review log) or run the seeded eval "
              "(--score --record). Nothing to roll up.")
        return
    print("\n  reviewer               seeded:catch  FP     real:fires  resolved  dismissed")
    print("  " + "-" * 76)
    for rev in sorted(by_rev):
        r = by_rev[rev]
        print(f"  {rev:22} {pct(r['catch_rate'])}       {pct(r['fp_rate'])}   "
              f"{r['fires']}/{r['ran']:<7}  {pct(r['resolution_rate'])}     {pct(r['dismiss_rate'])}")
    print("\n  verdicts:")
    for rev in sorted(by_rev):
        print(f"    {rev:22} {by_rev[rev]['verdict']}")


def _selftest() -> int:
    fails = 0

    def ok(cond, msg):
        nonlocal fails
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    trend = [{"ts": "t", "reviewer_files_hash": "h", "scoreboard": {
        "security": {"catch_rate": 1.0, "fp_rate": 0.0},
        "data-access": {"catch_rate": 0.4, "fp_rate": 0.6},
        "api-contract": {"catch_rate": 0.9, "fp_rate": 0.1}}}]
    log = (
        [{"reviewer": "security", "fired": True, "outcome": "fixed"}] * 2 +
        [{"reviewer": "security", "fired": False}] * 1 +
        [{"reviewer": "api-contract", "fired": True, "outcome": "dismissed"}] * 3 +
        [{"reviewer": "observability", "fired": False}] * 12 +   # only in log, no seeded row
        [{"reviewer": "observability", "fired": True, "outcome": "fixed"}] * 1
    )
    r = rollup(trend, log)

    ok(r["data-access"]["verdict"].startswith("PRUNE"), "data-access (fp>catch) -> PRUNE")
    ok(r["security"]["verdict"].startswith("KEEP"), "security (net-positive) -> KEEP")
    ok(r["security"]["resolution_rate"] == 1.0, "security resolution = fixed/fires (2/2)")
    ok(r["api-contract"]["dismiss_rate"] == 1.0, "api-contract dismiss = 3/3")
    ok("observability" in r and r["observability"]["catch_rate"] is None,
       "log-only reviewer appears with no seeded numbers")
    ok("TIER-DOWN" in r["observability"]["verdict"] or "NO DATA" in r["observability"]["verdict"]
       or "KEEP?" in r["observability"]["verdict"], "log-only reviewer gets a real-world/no-data verdict")
    ok(rollup([], [])  == {}, "empty inputs -> empty rollup")

    print(f"\nreview-rollup.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    root = fx.repo_root() or "."
    by_rev = rollup(_read_jsonl(os.path.join(root, TREND)), _read_jsonl(os.path.join(root, LOG)))
    print_table(by_rev)
    sys.exit(0)
