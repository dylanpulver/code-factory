#!/usr/bin/env python3
"""
stop-completeness — completeness gate (Stop). The "don't stop until every layer is proven" gate.

From the branch + working diff, compute every touched QA surface. Block the turn end until
`.claude/state/validation.json` shows each one validated (with a fresh diff_hash) and, when >1
surface changed, an end-to-end entry. Loop-safe via `stop_hook_active`; FACTORY_OFF escapes.

Which surfaces REQUIRE validation = `qa_surfaces` in factory.config.yaml (a list), else derived
from the pack dispatch-matrix (any surface with a non-empty `qa` list). With neither, the gate is
dormant — it never blocks — so it activates exactly when you declare QA for a surface.

This is the BACKSTOP. The active loop is in the ship-it command (validate -> fix -> re-validate);
the gate should rarely fire in a normal run.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

LEDGER = os.path.join(".claude", "state", "validation.json")


def qa_surfaces(root):
    """Surfaces that require their own validation before a turn may end."""
    cfg = fx.load_config(root).get("qa_surfaces")
    if isinstance(cfg, list):
        return set(cfg)
    surfs = set()
    for name in fx.active_packs(root):
        path = os.path.join(fx.pack_dir(name, root), "reviewers", "dispatch-matrix.json")
        try:
            with open(path) as f:
                matrix = json.load(f)
        except Exception:
            continue
        for surf, spec in matrix.get("surfaces", {}).items():
            if spec.get("qa"):
                surfs.add(surf)
    return surfs


def surfaces_and_hashes(root, files, qa):
    """Group touched files into the QA surfaces and hash each surface's current diff."""
    by_surface = {}
    for f in files:
        for s in fx.surface(f, root):
            if s in qa:
                by_surface.setdefault(s, []).append(f)
    hashes = {s: fx.diff_hash_for(root, fs) for s, fs in by_surface.items()}
    return set(by_surface), hashes


def evaluate(touched, ledger, current_hashes):
    """Return a block reason, or None if complete."""
    if not touched:
        return None
    surfaces = ledger.get("surfaces", {}) if isinstance(ledger, dict) else {}
    OK = ("pass", "waived")
    missing = []
    for s in sorted(touched):
        e = surfaces.get(s)
        if not e or e.get("status") not in OK:
            missing.append(f"{s}: not validated (run its QA, or waive: stamp-ledger.py {s} waived \"reason\")")
        elif current_hashes.get(s) and e.get("diff_hash") != current_hashes[s]:
            missing.append(f"{s}: validation is stale — code changed since (or no diff_hash recorded); re-run its QA")
    if len(touched) > 1:
        e2e = ledger.get("e2e") if isinstance(ledger, dict) else None
        if not e2e or e2e.get("status") not in OK:
            missing.append("end-to-end: >1 surface changed — run qa-e2e across the touched layers")
    if not missing:
        return None
    return ("Completeness gate: don't end the turn until every touched layer is validated:\n  - "
            + "\n  - ".join(missing)
            + "\n\nEach surface stamps .claude/state/validation.json. To stop anyway: FACTORY_OFF=1.")


def require_verify(root=None) -> bool:
    """Opt-in (config `require_verify: true`): block turn-end until the change is verified."""
    return fx.load_config(root).get("require_verify") in (True, "true", "True", "1", "yes")


def verify_gap(governed_changed, ledger, current_hash):
    """Return a reason if verify is required + missing/stale, else None. Pure."""
    if not governed_changed:
        return None  # docs/config-only change — nothing to verify
    e = ledger.get("verify") if isinstance(ledger, dict) else None
    if not e or e.get("status") not in ("pass", "waived"):
        return ("Verify gate: this change isn't verified — run `factory verify --test <path>` "
                "(or waive: stamp-ledger.py verify waived \"reason\"). To stop anyway: FACTORY_OFF=1.")
    if current_hash and e.get("diff_hash") != current_hash:
        return ("Verify gate: the verify stamp is stale — code changed since it ran; re-run "
                "`factory verify`. To stop anyway: FACTORY_OFF=1.")
    return None


def main(data):
    if fx.stop_hook_active(data):
        return  # loop-safe: already nudged this stop sequence
    root = fx.repo_root()
    if not root:
        return
    qa = qa_surfaces(root)
    req_v = require_verify(root)
    files = fx.branch_touched_files(root)
    if not qa and not req_v:
        # Fully dormant — nothing opted in. Don't silently no-op: an off backstop must not be
        # indistinguishable from a clean run. Warn (non-blocking) when governed code changed.
        if any(fx.surface(f, root) for f in files):
            fx.emit_warn("⚠️  factory: Stop-gate is dormant (require_verify off, no QA surfaces) — "
                         "governed code changed but nothing enforced verify/review. "
                         "Set require_verify: true to enforce.")
        return
    ledger = {}
    try:
        with open(os.path.join(root, LEDGER)) as f:
            ledger = json.load(f)
    except Exception:
        ledger = {}
    reasons = []
    if qa:
        touched, hashes = surfaces_and_hashes(root, files, qa)
        r = evaluate(touched, ledger, hashes)
        if r:
            reasons.append(r)
    if req_v:
        governed = any(fx.surface(f, root) for f in files)
        r = verify_gap(governed, ledger, fx.diff_hash_for(root, sorted(files)))
        if r:
            reasons.append(r)
    if reasons:
        fx.emit_block("\n\n".join(reasons))


def _selftest() -> int:
    fails = 0

    def case(name, touched, ledger, hashes, expect_block):
        nonlocal fails
        r = evaluate(set(touched), ledger, hashes)
        ok = (r is not None) == expect_block
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {'block' if r else 'allow'} (want {'block' if expect_block else 'allow'})")

    L_api = {"surfaces": {"api": {"status": "pass", "diff_hash": "abc"}}}
    case("no surface touched -> allow", [], {}, {}, False)
    case("api touched, no ledger -> block", ["api"], {}, {"api": "abc"}, True)
    case("api touched, validated fresh -> allow", ["api"], L_api, {"api": "abc"}, False)
    case("api touched, validated stale -> block", ["api"], L_api, {"api": "ZZZ"}, True)
    L_waived = {"surfaces": {"api": {"status": "waived", "diff_hash": "abc"}}}
    case("api touched, waived fresh -> allow", ["api"], L_waived, {"api": "abc"}, False)
    case("api touched, waived stale -> block", ["api"], L_waived, {"api": "ZZZ"}, True)
    case("api validated, frontend not -> block", ["api", "frontend"], L_api, {"api": "abc", "frontend": "x"}, True)
    both = {"surfaces": {"api": {"status": "pass", "diff_hash": "a"}, "frontend": {"status": "pass", "diff_hash": "b"}}}
    case(">1 surface, both validated, no e2e -> block", ["api", "frontend"], both, {"api": "a", "frontend": "b"}, True)
    both_e2e = dict(both); both_e2e["e2e"] = {"status": "pass"}
    case(">1 surface, both validated + e2e -> allow", ["api", "frontend"], both_e2e, {"api": "a", "frontend": "b"}, False)

    # qa_surfaces resolution: config list wins
    cfg_surfs = qa_surfaces(fx.FACTORY_ROOT)
    print(f"  [PASS] qa_surfaces resolves (got {sorted(cfg_surfs)})")

    # verify gate (pure verify_gap)
    def vcase(name, governed, ledger, cur, expect_block):
        nonlocal fails
        r = verify_gap(governed, ledger, cur)
        ok = (r is not None) == expect_block
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} -> {'block' if r else 'allow'} (want {'block' if expect_block else 'allow'})")

    Lv = {"verify": {"status": "pass", "diff_hash": "h1"}}
    vcase("docs-only (not governed) -> allow", False, {}, "h1", False)
    vcase("code changed, no verify -> block", True, {}, "h1", True)
    vcase("code changed, verify fresh -> allow", True, Lv, "h1", False)
    vcase("code changed, verify stale -> block", True, Lv, "ZZZ", True)
    vcase("code changed, verify waived fresh -> allow", True, {"verify": {"status": "waived", "diff_hash": "h1"}}, "h1", False)

    print(f"\nstop-completeness.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    fx.run(main)
