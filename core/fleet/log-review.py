#!/usr/bin/env python3
"""
log-review — passive, FREE record of what the reviewer fleet did on a REAL run.

The reviewers already run inside /ship-it, so recording their verdicts costs ZERO extra tokens.
One record per (run x reviewer): did it fire, what it flagged, and what the drive did with the
flag — fixed (real value), dismissed (real-world noise), or waived (deferred). Appended to
.claude/state/review-log.jsonl; the rollup (review-rollup.py) turns it into per-reviewer
fire-rate / resolution-rate / dismiss-rate — the real-world half of the empirical loop.

HONEST: this is self-graded (the drive logs its own reviewers + its own resolution call), so it is
DIRECTIONAL drift signal, not ground truth. The objective half is the seeded eval
(eval-reviewers.py --score), which plants known bugs and needs no judge.

Usage:
  echo '<record | [records]>' | python3 core/fleet/log-review.py     # or --json '<...>'
  python3 core/fleet/log-review.py --selftest
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

LOG = os.path.join(".claude", "state", "review-log.jsonl")
OUTCOMES = ("fixed", "dismissed", "waived")


def validate_record(rec):
    """Errors (empty = valid). A fired finding must carry a disposition; a non-fire must not."""
    if not isinstance(rec, dict):
        return ["record is not an object"]
    errs = []
    if not rec.get("reviewer"):
        errs.append("missing reviewer")
    fired = rec.get("fired")
    if not isinstance(fired, bool):
        errs.append("fired must be true/false")
    outcome = rec.get("outcome")
    if fired is True and outcome not in OUTCOMES:
        errs.append(f"a fired finding needs outcome in {OUTCOMES} (got {outcome!r})")
    if fired is False and outcome is not None:
        errs.append("a non-fire must have outcome null")
    return errs


def make_record(payload, ts, diff_hash):
    fired = bool(payload.get("fired", False))
    return {
        "ts": ts,
        "diff_hash": diff_hash,
        "surface": payload.get("surface", ""),
        "reviewer": payload.get("reviewer", ""),
        "fired": fired,
        "findings": payload.get("findings", []) if fired else [],
        "outcome": payload.get("outcome") if fired else None,
    }


def append(root, records):
    out = os.path.join(root, LOG)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def main(argv):
    if "--json" in argv:
        i = argv.index("--json")
        raw = argv[i + 1] if i + 1 < len(argv) else ""
    else:
        raw = sys.stdin.read()
    try:
        payload = json.loads(raw or "")
    except Exception as e:
        print(f"log-review: bad JSON ({e})", file=sys.stderr)
        return 2
    payloads = payload if isinstance(payload, list) else [payload]
    root = fx.repo_root() or "."
    ts = datetime.now().isoformat(timespec="seconds")
    dh = fx.diff_hash_for(root, fx.branch_touched_files(root))
    recs = []
    for p in payloads:
        errs = validate_record(p)
        if errs:
            print(f"log-review: skipped {p.get('reviewer', '?') if isinstance(p, dict) else '?'}: "
                  f"{'; '.join(errs)}", file=sys.stderr)
        else:
            recs.append(make_record(p, ts, dh))
    if recs:
        append(root, recs)
        print(f"logged {len(recs)} review record(s) -> {LOG}")
        return 0
    return 2


def _selftest() -> int:
    fails = 0

    def ok(cond, msg):
        nonlocal fails
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails += 1

    ok(validate_record({"reviewer": "security", "fired": True, "outcome": "fixed"}) == [], "valid fired+fixed")
    ok(validate_record({"reviewer": "security", "fired": False, "outcome": None}) == [], "valid non-fire")
    ok(any("outcome" in e for e in validate_record({"reviewer": "security", "fired": True, "outcome": None})),
       "fired without outcome -> error")
    ok(any("non-fire" in e for e in validate_record({"reviewer": "security", "fired": False, "outcome": "fixed"})),
       "non-fire with outcome -> error")
    ok(any("reviewer" in e for e in validate_record({"fired": True, "outcome": "fixed"})),
       "missing reviewer -> error")

    r = make_record({"reviewer": "security", "surface": "api", "fired": True, "findings": ["x"], "outcome": "fixed"}, "t", "h")
    ok(r["reviewer"] == "security" and r["fired"] and r["outcome"] == "fixed" and r["ts"] == "t", "make_record shape")
    r2 = make_record({"reviewer": "data-access", "fired": False, "findings": ["ignored"], "outcome": "fixed"}, "t", "h")
    ok(r2["findings"] == [] and r2["outcome"] is None, "non-fire record drops findings/outcome")

    import tempfile
    d = tempfile.mkdtemp()
    append(d, [r, r])
    lines = [l for l in open(os.path.join(d, LOG)).read().splitlines() if l.strip()]
    ok(len(lines) == 2 and json.loads(lines[0])["reviewer"] == "security", "append writes one jsonl line per record")

    print(f"\nlog-review.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
