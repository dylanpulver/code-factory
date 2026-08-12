#!/usr/bin/env python3
"""
standards-check — real-time standards gate (PostToolUse: Edit|Write).

On every edit, diff the touched file and check ONLY the ADDED lines against the standards
rules. BLOCK -> {"decision":"block"} (model fixes it now). WARN -> stderr (advisory).

Rule sources (the engine is language-agnostic; the patterns are stack-specific):
  - CORE_UNIVERSAL  — language-agnostic security (secrets, literal credentials), in this file.
  - the active pack(s) `patterns/standards.json` — universal + per-surface rules, file globs,
    test-escape, service-console, client-secret. Loaded at runtime.

Invariants from `_factory`: fail-safe, added-lines-only, kill-switch. Detection isolated in
`scan()` so `--selftest` exercises it with synthetic examples (no git).
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

# Language-agnostic security rules — applied to every governed added line, regardless of pack.
CORE_UNIVERSAL = [
    (re.compile(r"(sk-ant-[A-Za-z0-9]|sk_live_|sk_test_|pk_live_|(AKIA|ASIA)[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY)"),
     "BLOCK", "sec/hardcoded-secret", "move to a secret manager / env; never commit"),
    (re.compile(r"\b(password|secret|api[_-]?key|apikey|token|dsn)\s*[:=]\s*['\"][^'\"]{12,}['\"]", re.I),
     "BLOCK", "sec/literal-credential", "use an env var; never inline a credential string"),
]

_STD_CACHE: dict = {}


def _compile_rules(raw):
    out = []
    for r in raw or []:
        try:
            out.append((re.compile(r[0]), r[1], r[2], r[3]))
        except (re.error, IndexError):
            continue
    return out


def load_standards_for_packs(packs, root=None):
    """Compile CORE_UNIVERSAL + the named packs' standards.json into one ruleset. Used both for
    the active pack(s) and to evaluate a SPECIFIC pack in isolation (factory eval-patterns)."""
    root = root or fx.FACTORY_ROOT
    rs = {
        "file_globs": [], "universal": list(CORE_UNIVERSAL), "surface": {},
        "service_console": None, "test_escape": None, "client_secret": None, "client_marker": None,
    }
    import json
    for name in packs:
        path = os.path.join(fx.pack_dir(name, root), "patterns", "standards.json")
        try:
            with open(path, "r", errors="ignore") as f:
                data = json.load(f)
        except Exception:
            continue
        rs["file_globs"] += data.get("file_globs", [])
        rs["universal"] += _compile_rules(data.get("universal"))
        for surf, rules in data.get("surface", {}).items():
            rs["surface"].setdefault(surf, [])
            rs["surface"][surf] += _compile_rules(rules)
        if rs["service_console"] is None and data.get("service_console"):
            rs["service_console"] = _compile_rules([data["service_console"]])[0] if data["service_console"] else None
        if rs["test_escape"] is None and data.get("test_escape"):
            try:
                rs["test_escape"] = re.compile(data["test_escape"])
            except re.error:
                pass
        if rs["client_marker"] is None and data.get("client_marker"):
            try:
                rs["client_marker"] = re.compile(data["client_marker"], re.M)
            except re.error:
                pass
        if rs["client_secret"] is None and data.get("client_secret"):
            cs = data["client_secret"]
            try:
                rs["client_secret"] = (re.compile(cs[0]), cs[1], cs[2])
            except (re.error, IndexError):
                pass
    return rs


def load_standards(root=None):
    """The active pack(s) ruleset (cached per root)."""
    root = root or fx.FACTORY_ROOT
    if root in _STD_CACHE:
        return _STD_CACHE[root]
    rs = load_standards_for_packs(fx.active_packs(root), root)
    _STD_CACHE[root] = rs
    return rs


def checks_for(rs, surfaces, is_test):
    checks = list(rs["universal"])
    for s in surfaces:
        checks += rs["surface"].get(s, [])
    if "service" in surfaces and not is_test and rs["service_console"]:
        checks.append(rs["service_console"])
    return checks


def scan_with(added, rs, surfaces, is_test, is_client):
    """Pure detection from an explicit ruleset + surface set — pack-independent (testable)."""
    checks = checks_for(rs, surfaces, is_test)
    blocks, warns = [], []
    for lineno, text in added:
        if is_test and rs["test_escape"] and rs["test_escape"].search(text):
            continue  # tests may use escape hatches deliberately
        for rx, tier, rid, fix in checks:
            if rx.search(text):
                entry = f"  L{lineno} [{rid}] {text.strip()[:90]}  -> {fix}"
                (blocks if tier == "BLOCK" else warns).append(entry)
        if is_client and "frontend" in surfaces and rs["client_secret"]:
            rx, rid, fix = rs["client_secret"]
            if rx.search(text):
                blocks.append(f"  L{lineno} [{rid}] {text.strip()[:90]}  -> {fix}")
    return blocks, warns


def scan(path, added, is_client=False, root=None):
    """Resolve the active ruleset + the path's surfaces, then detect."""
    return scan_with(added, load_standards(root), fx.surface(path, root),
                     fx.IS_TEST(path), is_client)


def _file_governed_for_standards(rs, p):
    if not rs["file_globs"]:
        return True
    return any(re.search(g, p) for g in rs["file_globs"])


def main(data):
    fp = fx.file_path(data)
    if not fp:
        return
    p = fp.replace("\\", "/")
    root = fx.repo_root(fp)
    if not root:
        return
    rs = load_standards(root)
    if not _file_governed_for_standards(rs, p):
        return
    if not fx.is_governed(p, root):
        return
    added = fx.added_lines(root, fp)
    if not added:
        return
    is_client = False
    if "frontend" in fx.surface(p, root) and rs["client_marker"]:
        try:
            with open(fp, "r", errors="ignore") as f:
                is_client = bool(rs["client_marker"].search(f.read(4000)))
        except Exception:
            is_client = False
    blocks, warns = scan(p, added, is_client, root)
    if warns:
        fx.emit_warn("⚠️  factory standards (advisory):\n" + "\n".join(warns[:12]))
    if blocks:
        reason = ("Standards gate blocked added lines that violate enforced rules. Fix these, then continue:\n"
                  + "\n".join(blocks[:15])
                  + "\n\nIf a block is a genuine false positive, say so explicitly and proceed; otherwise correct the code.")
        fx.emit_block(reason)


def _selftest() -> int:
    fails = 0

    # Synthetic ruleset — exercises the ENGINE (tiers, surface routing, test-escape,
    # service-console, client-secret) independently of any pack's patterns.
    RS = {
        "file_globs": [],
        "universal": [
            (re.compile(r"\bBADBLOCK\b"), "BLOCK", "x/block", "remove it"),
            (re.compile(r"\bsoftwarn\b"), "WARN", "x/warn", "tidy it"),
        ],
        "surface": {
            "web": [(re.compile(r"\bDANGER\b"), "WARN", "web/danger", "fix it")],
        },
        "service_console": (re.compile(r"\blog\("), "WARN", "obs/console", "use a logger"),
        "test_escape": re.compile(r"ESCAPE"),
        "client_secret": (re.compile(r"\bRAWSECRET\b"), "x/client-secret", "server-side only"),
        "client_marker": None,
    }

    def case(name, lines, surfaces, expect_block, expect_warn=None, is_test=False, is_client=False):
        nonlocal fails
        added = [(i + 1, ln) for i, ln in enumerate(lines)]
        blocks, warns = scan_with(added, RS, set(surfaces), is_test, is_client)
        ok = (len(blocks) > 0) == expect_block
        if expect_warn is not None:
            ok = ok and ((len(warns) > 0) == expect_warn)
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  (blocks={len(blocks)} warns={len(warns)})")

    # tier routing
    case("universal BLOCK fires", ["x BADBLOCK y"], ["service"], True)
    case("universal WARN only", ["a softwarn b"], ["service"], False, expect_warn=True)
    case("surface rule fires on its surface", ["a DANGER b"], ["web"], False, expect_warn=True)
    case("surface rule silent off its surface", ["a DANGER b"], ["service"], False, expect_warn=False)
    # service-console: applies to service, not in tests
    case("service console warns", ["log('hi')"], ["service"], False, expect_warn=True)
    case("service console skipped in test", ["log('hi')"], ["service"], False, expect_warn=False, is_test=True)
    # test-escape skips escape-hatch lines in tests
    case("BLOCK suppressed by ESCAPE in test", ["BADBLOCK /* ESCAPE */"], ["service"], False, is_test=True)
    case("BLOCK still fires in non-test", ["BADBLOCK here"], ["service"], True)
    # client-secret only when frontend + is_client
    case("client secret blocks (frontend+client)", ["const k = RAWSECRET"], ["frontend"], True, is_client=True)
    case("client secret silent when not client", ["const k = RAWSECRET"], ["frontend"], False, expect_warn=False)
    case("client secret silent off frontend", ["const k = RAWSECRET"], ["service"], False, expect_warn=False)
    # clean
    case("clean line", ["const ok = compute()"], ["service"], False, expect_warn=False)

    # smoke: the REAL active pack loads + scans a clean line without crashing (pack-agnostic)
    b, w = scan("x", [(1, "a perfectly clean line")], root=fx.FACTORY_ROOT)
    ok = isinstance(b, list) and isinstance(w, list)
    if not ok:
        fails += 1
    print(f"  [{'PASS' if ok else 'FAIL'}] active pack ruleset loads + scans (smoke)")

    print(f"\nstandards-check.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    fx.run(main)
