#!/usr/bin/env python3
"""
core/fleet/dispatch.py — the deterministic "which reviewers/QA" computation.

Given a set of changed files, classify each with `_factory.surface()`, read the active
pack(s) `dispatch-matrix.json`, and return the reviewer set + QA set to run. The ship-it
command calls this, then spawns the named reviewers (Opus, in parallel) via the Agent tool
and runs the bounded review-until-clean loop.

This is the engine half (deterministic routing). The loop + the LLM judgment live in the
ship-it command. Keeping routing here makes it testable and keeps the command thin.

Usage:
  python3 core/fleet/dispatch.py --files apps/api/src/x.ts packages/db/q.ts
  python3 core/fleet/dispatch.py --selftest
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402


def _matrices(root: str | None = None) -> list:
    out = []
    packs = fx.active_packs(root)
    for name in packs:
        path = os.path.join(fx.pack_dir(name, root), "reviewers", "dispatch-matrix.json")
        try:
            with open(path, "r", errors="ignore") as f:
                out.append(json.load(f))
        except Exception as e:
            # a missing/malformed matrix silently drops the whole pack's routing — even the
            # `always` reviewers — so a governed file reports "clean". Never silent; make it loud.
            sys.stderr.write(f"factory: pack '{name}' dispatch-matrix.json unreadable ({path}): {e}\n")
    if packs and not out:
        sys.stderr.write(f"factory: WARNING — {len(packs)} active pack(s) but no dispatch-matrix loaded; "
                         "routing 0 reviewers. Fix the pack config before trusting this run.\n")
    return out


def compute(files, root: str | None = None) -> dict:
    """Return {surfaces, reviewers, qa} for a set of changed files."""
    surfaces: set = set()
    for fp in files:
        surfaces |= fx.surface(fp, root)

    reviewers: set = set()
    qa: list = []
    for matrix in _matrices(root):
        reviewers |= set(matrix.get("always", []))
        smap = matrix.get("surfaces", {})
        for surf in surfaces:
            spec = smap.get(surf, {})
            reviewers |= set(spec.get("reviewers", []))
            for q in spec.get("qa", []):
                if q not in qa:
                    qa.append(q)
    return {
        "surfaces": sorted(surfaces),
        "reviewers": sorted(reviewers),
        "qa": qa,
    }


def main(argv) -> int:
    if "--files" in argv:
        i = argv.index("--files")
        files = argv[i + 1:]
        print(json.dumps(compute(files), indent=2))
        return 0
    # default: classify the current branch's touched files
    root = fx.repo_root() or fx.FACTORY_ROOT
    files = sorted(fx.branch_touched_files(root))
    print(json.dumps({"files": files, **compute(files, root)}, indent=2))
    return 0


def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        if not cond:
            fails += 1
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    root = fx.FACTORY_ROOT

    # Pack-agnostic routing invariants (hold for ANY active pack):
    # the `always` set = what an empty/ungoverned diff routes to.
    base = set(compute([], root)["reviewers"])
    check(f"always set is non-empty (got {sorted(base)})", len(base) > 0)

    r = compute(["node_modules/dep/index.js"], root)
    check(f"ungoverned file -> only the always set (got {r['reviewers']})",
          set(r["reviewers"]) == base)
    check("ungoverned file has no surfaces", r["surfaces"] == [])

    # a governed file (per the active pack) yields a superset of `always`
    files = sorted(fx.branch_touched_files(root)) or []
    gov = next((f for f in files if fx.surface(f, root)), None)
    if gov:
        r = compute([gov], root)
        check(f"governed file ({gov}) -> superset of always (got {r['reviewers']})",
              base <= set(r["reviewers"]))
    else:
        check("governed-file superset check (no governed file in diff; skipped)", True)

    # union monotonicity: adding files never drops a reviewer
    r2 = compute(["a/x", "b/y"], root)
    check("multi-file union >= always", base <= set(r2["reviewers"]))

    print(f"\ndispatch.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
