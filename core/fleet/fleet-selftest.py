#!/usr/bin/env python3
"""
core/fleet/fleet-selftest.py — reviewer fleet structural self-test (anti-rot).

Structural guarantees about every active pack's review fleet (the LLM catch/pass of the
golden fixtures is an eval-time concern; this makes the *structure* unable to silently rot):
  - every reviewer is `model: opus` and read-only (no Write/Edit tools)
  - every reviewer ships a Bad + Good golden fixture
  - every reviewer named in the matrix (always + surfaces) has a file
  - every reviewer file is referenced by the matrix (no orphan)
  - the dispatch matrix loads and routes (delegated to dispatch.py's own selftest)

Portable: validates the PACK contents, not a consuming repo's directory layout — so it runs
green anywhere the pack is checked out (glob-liveness against real app dirs is a per-repo
concern, deferred to the consuming repo's factory-check).

Run: python3 core/fleet/fleet-selftest.py --selftest
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402


def parse(path: str) -> dict:
    txt = open(path, errors="ignore").read()
    fm = re.search(r"^---\s*\n(.*?)\n---", txt, re.S)
    fmtxt = fm.group(1) if fm else ""
    model = (re.search(r"^model:\s*(\S+)", fmtxt, re.M) or [None, None])[1]
    tools = (re.search(r"^tools:\s*(.+)$", fmtxt, re.M) or [None, ""])[1]
    key = os.path.basename(path).replace("-reviewer.md", "").replace(".md", "")
    return {
        "key": key, "model": model, "tools": tools,
        "has_bad": "### Bad (must flag)" in txt,
        "has_good": "### Good (must pass)" in txt,
    }


def check_model(model) -> bool:
    return model == "opus"


def all_packs():
    """Every authored pack (a dir under packs/ with a surface.json), not just the active ones —
    an inactive pack must not silently rot."""
    base = os.path.join(fx.FACTORY_ROOT, "packs")
    names = []
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "surface.json")):
            names.append(os.path.basename(d))
    return names


def check_pack(name: str, ok) -> None:
    rdir = os.path.join(fx.pack_dir(name), "reviewers")
    files = [f for f in glob.glob(os.path.join(rdir, "*.md"))
             if os.path.basename(f).lower() != "readme.md"]
    ok(len(files) >= 1, f"[{name}] >=1 reviewer file (found {len(files)})")

    reviewers = {}
    for f in files:
        r = parse(f)
        reviewers[r["key"]] = r
        ok(check_model(r["model"]), f"[{name}] {r['key']}: model is opus (got {r['model']})")
        ok("Write" not in r["tools"] and "Edit" not in r["tools"],
           f"[{name}] {r['key']}: read-only tools")
        ok(r["has_bad"] and r["has_good"], f"[{name}] {r['key']}: ships Bad + Good fixtures")

    try:
        matrix = json.load(open(os.path.join(rdir, "dispatch-matrix.json")))
    except Exception as e:
        ok(False, f"[{name}] dispatch-matrix.json loads ({e})")
        return

    in_matrix = set(matrix.get("always", []))
    for spec in matrix.get("surfaces", {}).values():
        in_matrix |= set(spec.get("reviewers", []))

    for r in sorted(in_matrix):
        ok(r in reviewers, f"[{name}] matrix reviewer '{r}' has an agent file")
    for key in sorted(reviewers):
        ok(key in in_matrix, f"[{name}] reviewer '{key}' referenced in matrix (not orphaned)")

    # Surface name is the join key across surface.json (emits) <-> dispatch-matrix (routes on) <->
    # standards.json (gates on). Nothing else checks the two sides agree, so a rename on one side
    # silently drops that surface's reviewers/QA and still reports "clean". Assert equality: a
    # matrix key surface.json can't emit is dead routing; an emitted surface the matrix ignores
    # means files route to only `always`. Either direction is a silent gate-drop -> fail loud.
    try:
        sj = json.load(open(os.path.join(fx.pack_dir(name), "surface.json")))
        emitted = set()
        for rule in sj.get("rules", []):
            emitted |= set(rule.get("surfaces", []))
        mkeys = set(matrix.get("surfaces", {}).keys())
        ok(emitted == mkeys,
           f"[{name}] surface vocabulary agrees (surface.json emits == matrix keys) — "
           f"emit-only={sorted(emitted - mkeys)} matrix-only={sorted(mkeys - emitted)}")
    except Exception as e:
        ok(False, f"[{name}] surface.json loads for vocab check ({e})")

    # surface fixtures — keeps the pack's topology from silently rotting
    tpath = os.path.join(fx.pack_dir(name), "surface.tests.json")
    if os.path.exists(tpath):
        try:
            cases = json.load(open(tpath)).get("cases", {})
        except Exception as e:
            ok(False, f"[{name}] surface.tests.json loads ({e})")
            cases = {}
        for path, expect in cases.items():
            got = fx.surface_for_pack(path, name)
            ok(got == set(expect), f"[{name}] surface({path}) == {sorted(expect)} (got {sorted(got)})")


def _selftest() -> int:
    fails = []

    def ok(cond, msg):
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
        if not cond:
            fails.append(msg)

    # logic checks (prove the test itself works)
    ok(not check_model("sonnet"), "check_model rejects sonnet")
    ok(check_model("opus"), "check_model accepts opus")

    packs = all_packs()
    ok(len(packs) >= 1, f">=1 pack authored (found {packs})")
    for name in packs:
        check_pack(name, ok)

    print(f"\nfleet-selftest.py: {'ALL PASS' if not fails else str(len(fails)) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest())
