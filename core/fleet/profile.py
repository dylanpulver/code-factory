#!/usr/bin/env python3
"""
profile — what the factory knows about a SPECIFIC repo (so it doesn't re-derive it every drive).

The generic pack is a guess; the profile is the truth for THIS repo: where things actually live
(Map), the real toolchain, the repo's idioms (how it does auth / data / errors), hotspots, past
findings, decisions. Lives at `.factory/profile.md` — repo-local, human-readable, committable.

- SEEDED by `factory profile init` (sniffs structure + toolchain — the adaptivity half).
- GROWN by each ship-it drive (`factory profile add <section> "<line>"` — the memory half).
- VERIFIED ON USE: entries are claims; before trusting one (e.g. "auth via X"), confirm it still
  holds (grep), update/drop stale ones. Repos change — this is how the profile self-heals.

Pure logic (sniffing, rendering, section-append) is isolated for --selftest; file IO wraps it.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _factory as fx  # noqa: E402

PROFILE = os.path.join(".factory", "profile.md")
SECTIONS = ["Map", "Toolchain", "Idioms", "Hotspots", "Findings", "Decisions"]

HEADER = (
    "# Repo profile — what the factory knows about THIS repo\n\n"
    "> Claims here are **verified on use**: before trusting an entry (e.g. \"auth via X\"), confirm it\n"
    "> still holds (grep the symbol/path); update or drop stale ones. Repos change — this self-heals.\n"
    "> Seeded by `factory profile init`, grown by each ship-it drive. Human-editable.\n"
)


# --------------------------------------------------------------------------- #
# Pure: sniff toolchain + map
# --------------------------------------------------------------------------- #
def detect_pm(files: set) -> str:
    if "pnpm-lock.yaml" in files:
        return "pnpm"
    if "yarn.lock" in files:
        return "yarn"
    if "package-lock.json" in files:
        return "npm"
    return "npm"


def detect_toolchain(files: set, pkg: dict) -> dict:
    if "pubspec.yaml" in files:
        return {"install": "flutter pub get", "test": "flutter test", "lint": "flutter analyze"}
    if "package.json" not in files:
        return {}
    pm = detect_pm(files)
    scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})} if isinstance(pkg, dict) else {}
    tc = {"install": f"{pm} install"}
    if "test" in scripts:
        tc["test"] = f"{pm} test"
    elif any("vitest" in d for d in deps):
        tc["test"] = f"{pm} vitest run"
    elif any("jest" in d for d in deps):
        tc["test"] = f"{pm} jest"
    if "lint" in scripts:
        tc["lint"] = f"{pm} lint"
    if "build" in scripts:
        tc["build"] = f"{pm} build"
    return tc


MAP_CANDIDATES = [
    ("app/api", "api, service"), ("src/app/api", "api, service"), ("apps/api", "api, service"),
    ("src/components", "frontend"), ("components", "frontend"),
    ("src/app", "frontend"), ("app", "frontend"),
    ("supabase", "data"), ("prisma", "database"), ("packages", "packages"),
    ("lib/widgets", "ui"), ("lib/services", "service"), ("lib/screens", "ui"),
]


def detect_map(dirs: set) -> list:
    """dirs = set of repo-relative directory paths present. Returns [(path, surfaces)]."""
    return [(p, s) for p, s in MAP_CANDIDATES if p in dirs]


def render_seed(toolchain: dict, map_hints: list) -> str:
    out = [HEADER, "## Map", ""]
    if map_hints:
        for p, s in map_hints:
            out.append(f"- `{p}/` → {s}")
    else:
        out.append("- _(none detected — fill in where your surfaces live)_")
    out += ["", "## Toolchain", ""]
    for k in ("install", "test", "lint", "build"):
        if k in toolchain:
            out.append(f"- {k}: `{toolchain[k]}`")
    for sec in ("Idioms", "Hotspots", "Findings", "Decisions"):
        out += ["", f"## {sec}", "", f"<!-- grown per drive: how this repo does {sec.lower()} -->"]
    return "\n".join(out) + "\n"


def add_to_text(text: str, section: str, line: str) -> str:
    """Append `- line` under `## section`, creating the section if missing. Pure."""
    bullet = f"- {line}"
    marker = f"## {section}"
    if marker not in text:
        return text.rstrip() + f"\n\n{marker}\n\n{bullet}\n"
    lines = text.splitlines()
    out, i = [], 0
    while i < len(lines):
        out.append(lines[i])
        if lines[i].strip() == marker:
            # find end of this section (next "## " or EOF), insert before it
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                out.append(lines[j])
                j += 1
            # trim trailing blanks/comments we appended, then add the bullet
            while out and (out[-1].strip() == "" or out[-1].strip().startswith("<!--")):
                out.pop()
            out.append(bullet)
            out.append("")
            i = j
            continue
        i += 1
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #
def _sniff(root: str):
    files = {f for f in os.listdir(root)} if os.path.isdir(root) else set()
    pkg = {}
    if "package.json" in files:
        try:
            pkg = json.load(open(os.path.join(root, "package.json")))
        except Exception:
            pkg = {}
    dirs = set()
    for base in ("", "src"):
        d = os.path.join(root, base) if base else root
        if os.path.isdir(d):
            for name in os.listdir(d):
                rel = os.path.join(base, name) if base else name
                if os.path.isdir(os.path.join(root, rel)):
                    dirs.add(rel.replace("\\", "/"))
    # one level deeper for app/api, lib/widgets, etc.
    for parent in ("app", "src/app", "apps", "lib"):
        d = os.path.join(root, parent)
        if os.path.isdir(d):
            for name in os.listdir(d):
                if os.path.isdir(os.path.join(d, name)):
                    dirs.add(f"{parent}/{name}")
    return detect_toolchain(files, pkg), detect_map(dirs)


def load(root: str | None = None) -> str:
    root = fx.work_root(root)
    try:
        return open(os.path.join(root, PROFILE)).read()
    except Exception:
        return ""


def seed(root: str | None = None, force: bool = False) -> str:
    root = fx.work_root(root)
    path = os.path.join(root, PROFILE)
    if os.path.exists(path) and not force:
        return f"profile exists at {PROFILE} (use --force to re-seed Map/Toolchain)"
    tc, mp = _sniff(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(render_seed(tc, mp))
    return f"seeded {PROFILE} (toolchain: {', '.join(tc) or 'none'}; map: {len(mp)} hints)"


def add(root: str | None, section: str, line: str) -> str:
    root = fx.work_root(root)
    path = os.path.join(root, PROFILE)
    text = load(root) or (HEADER + "\n")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(add_to_text(text, section, line))
    return f"added to {section}: {line}"


def main(argv) -> int:
    cmd = argv[0] if argv else "show"
    if cmd in ("init", "seed"):
        print(seed(force="--force" in argv))
    elif cmd == "show":
        print(load() or "(no profile — run `factory profile init`)")
    elif cmd == "add" and len(argv) >= 3:
        print(add(None, argv[1], " ".join(argv[2:])))
    else:
        print("usage: factory profile {init [--force] | show | add <section> <line>}", file=sys.stderr)
        return 2
    return 0


def _selftest() -> int:
    fails = 0

    def ok(cond, msg):
        nonlocal fails
        if not cond:
            fails += 1
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")

    # toolchain sniff
    tc = detect_toolchain({"package.json", "pnpm-lock.yaml"},
                          {"scripts": {"lint": "eslint"}, "devDependencies": {"vitest": "1"}})
    ok(tc.get("install") == "pnpm install", f"pnpm install detected (got {tc.get('install')})")
    ok(tc.get("test") == "pnpm vitest run", f"vitest test cmd (got {tc.get('test')})")
    ok(tc.get("lint") == "pnpm lint", "lint from scripts")
    ok(detect_toolchain({"pubspec.yaml"}, {})["test"] == "flutter test", "flutter toolchain")

    # map sniff
    mp = detect_map({"app/api", "src/components", "supabase"})
    ok(("app/api", "api, service") in mp and ("src/components", "frontend") in mp, "map detects real dirs")

    # render + append
    seeded = render_seed({"install": "pnpm install", "test": "pnpm vitest run"}, [("app/api", "api, service")])
    ok("## Map" in seeded and "app/api" in seeded and "pnpm vitest run" in seeded, "seed renders sections")
    t2 = add_to_text(seeded, "Idioms", "auth: Firebase session cookie")
    ok("auth: Firebase session cookie" in t2, "add inserts a bullet")
    ok(t2.count("## Idioms") == 1, "add doesn't duplicate the section")
    t3 = add_to_text(seeded, "NewSec", "x")
    ok("## NewSec" in t3 and "- x" in t3, "add creates a missing section")

    print(f"\nprofile.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(_selftest() if "--selftest" in sys.argv else main(sys.argv[1:]))
