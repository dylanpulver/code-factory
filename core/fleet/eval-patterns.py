#!/usr/bin/env python3
"""
eval-patterns — Tier-1 eval for the DETERMINISTIC standards gate.

Runs each pack's held-out pattern fixtures (packs/<pack>/patterns/standards.tests.json) through
the real standards-check engine and reports, per rule:
  - did it FIRE on lines that should trigger it (recall / true positives)?
  - did it stay SILENT on lines that should not (precision / false positives)?

Rigor is free here: regexes are deterministic, no LLM, no subjectivity. Non-circular as long as
the fixtures are authored independently of the patterns. A failing case fails the gate.

Run:  factory eval-patterns        (readable report)
      python3 core/fleet/eval-patterns.py --selftest   (gate; nonzero on any failed case)
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

# load the hyphenated standards-check module
_spec = importlib.util.spec_from_file_location(
    "standards_check", os.path.join(fx.FACTORY_HOME, "core", "hooks", "standards-check.py"))
sc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sc)

RULE_RE = re.compile(r"^\s*L\d+ \[([^\]]+)\]")


def fired_rules(entries):
    out = set()
    for e in entries:
        m = RULE_RE.match(e)
        if m:
            out.add(m.group(1))
    return out


def packs_with_fixtures():
    base = os.path.join(fx.FACTORY_HOME, "packs")
    names = []
    for d in sorted(glob.glob(os.path.join(base, "*"))):
        if os.path.isfile(os.path.join(d, "patterns", "standards.tests.json")):
            names.append(os.path.basename(d))
    return names


def eval_pack(name):
    path = os.path.join(fx.pack_dir(name), "patterns", "standards.tests.json")
    try:
        cases = json.load(open(path)).get("cases", [])
    except Exception as e:
        return None, [(None, False, f"could not load fixtures: {e}")]
    rs = sc.load_standards_for_packs([name])
    per_rule = {}
    results = []
    for c in cases:
        f, line, expect = c.get("file", ""), c.get("line", ""), c.get("expect", "")
        rule, is_client = c.get("rule"), bool(c.get("client"))
        surfaces = fx.surface_for_pack(f, name)
        blocks, warns = sc.scan_with([(1, line)], rs, surfaces, fx.IS_TEST(f), is_client)
        fb, fw = fired_rules(blocks), fired_rules(warns)
        fired = fb | fw
        if expect == "block":
            ok = (rule in fb) if rule else (len(blocks) > 0)
        elif expect == "warn":
            ok = ((rule in fw) if rule else len(warns) > 0) and len(blocks) == 0
        else:  # clean
            ok = (rule not in fired) if rule else (len(fired) == 0)
        if rule:
            d = per_rule.setdefault(rule, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
            positive = expect in ("block", "warn")
            did = rule in fired
            d["tp" if (positive and did) else "fn" if positive else "fp" if did else "tn"] += 1
        detail = f"{expect:5} {rule or '-':28} {f}  ::  {line.strip()[:50]}"
        if not ok:
            detail += f"   [fired: {sorted(fired) or 'none'}]"
        results.append((c, ok, detail))
    return per_rule, results


def report(packs):
    fails = 0
    for name in packs:
        per_rule, results = eval_pack(name)
        print(f"\n=== pack: {name} ===")
        for _, ok, detail in results:
            if not ok:
                fails += 1
            print(f"  [{'PASS' if ok else 'FAIL'}] {detail}")
        if per_rule:
            print(f"  -- per-rule precision/recall ({name}) --")
            for rule in sorted(per_rule):
                d = per_rule[rule]
                p_den, r_den = d["tp"] + d["fp"], d["tp"] + d["fn"]
                p = f"{d['tp']/p_den:.2f}" if p_den else "  - "
                r = f"{d['tp']/r_den:.2f}" if r_den else "  - "
                print(f"     {rule:28} P={p} R={r}  (tp={d['tp']} fp={d['fp']} fn={d['fn']})")
    return fails


def _selftest() -> int:
    packs = packs_with_fixtures()
    if not packs:
        print("  [PASS] no pattern fixtures yet (nothing to eval)")
        print("\neval-patterns.py: ALL PASS")
        return 0
    fails = report(packs)
    print(f"\neval-patterns.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(0 if report(packs_with_fixtures()) == 0 else 1)
