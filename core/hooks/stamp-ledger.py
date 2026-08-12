#!/usr/bin/env python3
"""
stamp-ledger — record a validation result the completeness gate trusts.

Usage:
  python3 core/hooks/stamp-ledger.py <surface|e2e> <pass|fail|waived> "evidence text"

Computes the surface's current diff_hash with the SAME logic the gate uses
(fx.diff_hash_for), so a stamp made now stays "fresh" until the code changes again.
Called by factory-check / the per-surface QA commands / qa-e2e.

`waived` = an auditable "in the diff but not this work's to validate" (e.g. inherited from a
stacked branch). The gate treats it like pass, but it goes stale if the surface changes again.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

LEDGER = os.path.join(".claude", "state", "validation.json")


def load(root):
    try:
        with open(os.path.join(root, LEDGER)) as f:
            return json.load(f)
    except Exception:
        return {}


def stamp(root, target, status, evidence, ts="manual"):
    ledger = load(root)
    if not isinstance(ledger, dict):
        ledger = {}
    if target == "e2e":
        ledger["e2e"] = {"status": status, "evidence": evidence, "ts": ts}
    elif target == "verify":
        # verify is whole-change: hash ALL touched files so the gate can check freshness
        files = fx.branch_touched_files(root)
        ledger["verify"] = {"status": status, "evidence": evidence, "ts": ts,
                            "diff_hash": fx.diff_hash_for(root, files)}
    else:
        files = [f for f in fx.branch_touched_files(root) if target in fx.surface(f, root)]
        entry = {"status": status, "evidence": evidence, "ts": ts,
                 "diff_hash": fx.diff_hash_for(root, files)}
        ledger.setdefault("surfaces", {})[target] = entry
    out = os.path.join(root, LEDGER)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(ledger, f, indent=2)
    return ledger


def main(argv):
    if len(argv) < 2:
        print("usage: stamp-ledger.py <surface|e2e> <pass|fail|waived> \"evidence\"", file=sys.stderr)
        return 2
    root = fx.repo_root() or "."
    target, status = argv[0], argv[1]
    evidence = argv[2] if len(argv) > 2 else ""
    stamp(root, target, status, evidence)
    print(f"stamped {target}={status} in {LEDGER}")
    return 0


def _selftest():
    import tempfile, subprocess
    fails = 0
    d = tempfile.mkdtemp()
    subprocess.run(["git", "-C", d, "init", "-q"], check=False)
    led = stamp(d, "api", "pass", "direct calls green", ts="t")
    ok = led.get("surfaces", {}).get("api", {}).get("status") == "pass"
    print(f"  [{'PASS' if ok else 'FAIL'}] stamps a surface entry"); fails += 0 if ok else 1
    led = stamp(d, "e2e", "pass", "cross-layer green", ts="t")
    ok = led.get("e2e", {}).get("status") == "pass"
    print(f"  [{'PASS' if ok else 'FAIL'}] stamps the e2e entry"); fails += 0 if ok else 1
    ok = "api" in led.get("surfaces", {})
    print(f"  [{'PASS' if ok else 'FAIL'}] merges without clobbering"); fails += 0 if ok else 1
    led = stamp(d, "api", "waived", "inherited from stacked branch", ts="t")
    ok = led.get("surfaces", {}).get("api", {}).get("status") == "waived"
    print(f"  [{'PASS' if ok else 'FAIL'}] supports a waiver"); fails += 0 if ok else 1
    print(f"\nstamp-ledger.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main(sys.argv[1:]))
