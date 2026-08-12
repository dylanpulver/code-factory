#!/usr/bin/env python3
"""
code-factory — shared core library (language-agnostic engine).

Every factory hook imports this so the cross-cutting behavior is defined once:
fail-safe execution, the kill-switch, stdin/env parsing, repo-root resolution,
added-lines diffing, the path->surface classifier, and the block/warn protocol.

Generalized from a production monorepo's factory. THE KEY CHANGE: the surface map is no longer
hardcoded here — core loads it from the active pack(s) named in `factory.config.yaml`.
Core never knows your repo's topology or language; the pack declares it.

Design invariants (see docs/PLAN.md §6):
- FAIL SAFE: any internal error -> allow the action (never block on a hook bug). `run()` enforces it.
- KILL SWITCH: FACTORY_OFF=1 disables every gate; FACTORY_WARN_ONLY=1 downgrades blocks to warnings.
- ADDED-LINES ONLY: edit gates inspect only the lines a change adds.
- OFFLINE + FAST: no network; git + regex only. Zero third-party deps (config parsed in-house).
- GRACEFUL DEGRADATION: missing config/pack -> empty surface map, never a crash.

Convention: every hook (and this module) supports `--selftest`.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

# FACTORY_HOME = where the engine + packs live (this checkout). Resolved from this file's
# location, or overridden by $FACTORY_HOME. The WORKING repo (the one being governed) is
# resolved separately via repo_root()/work_root() — so one global install can govern any repo.
FACTORY_HOME = os.environ.get("FACTORY_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FACTORY_ROOT = FACTORY_HOME  # back-compat alias (selftests pass this as the working root)


# --------------------------------------------------------------------------- #
# Kill switch
# --------------------------------------------------------------------------- #
def off() -> bool:
    return os.environ.get("FACTORY_OFF", "") not in ("", "0", "false", "False")


def warn_only() -> bool:
    return os.environ.get("FACTORY_WARN_ONLY", "") not in ("", "0", "false", "False")


def flag(name: str) -> bool:
    """Strict truthy read of a per-action override env var. Empty/0/false/no = off."""
    return os.environ.get(name, "") not in ("", "0", "false", "False", "no", "No")


# --------------------------------------------------------------------------- #
# Input parsing
# --------------------------------------------------------------------------- #
def read_input() -> dict:
    data: dict = {}
    try:
        raw = sys.stdin.read()
        if raw and raw.strip():
            data = json.loads(raw)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not data.get("tool_input"):
        try:
            env = os.environ.get("CLAUDE_TOOL_INPUT", "")
            if env:
                ti = json.loads(env)
                if isinstance(ti, dict):
                    data.setdefault("tool_input", ti)
        except Exception:
            pass
    return data


def tool_input(data: dict) -> dict:
    ti = data.get("tool_input")
    return ti if isinstance(ti, dict) else {}


def file_path(data: dict):
    return tool_input(data).get("file_path")


def command(data: dict) -> str:
    return tool_input(data).get("command") or ""


def stop_hook_active(data: dict) -> bool:
    return bool(data.get("stop_hook_active"))


# Global options that carry a VALUE (so the following token is skipped too) when locating the
# real subcommand. Anything else starting with `-` is a valueless global flag (--no-pager, etc).
_GLOBAL_VALUE_OPTS = {
    "git": {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"},
    "gh": {"-R", "--repo"},
}
_SHELL_SEP = {";", "&&", "||", "|", "&"}
_CMD_WRAPPERS = {"sudo", "env", "time", "nice", "command", "doas", "exec", "stdbuf", "nohup"}


def cli_subcommand(cmd: str, tool: str):
    """Parse a `git`/`gh` command to (subcommand, args), skipping global options — so a gate keys
    on the REAL subcommand, not `parts[1]`. Robust to `git -C dir push`, `git --no-pager commit`,
    `gh -R o/r pr merge`, and a leading `sudo`/`env`/`VAR=val`. The tool must be the primary command
    (only known wrappers/env-assignments may precede it) — so `echo git push` and a `git` in a later
    compound segment are NOT treated as the command. Returns (None, []) when `tool` isn't invoked."""
    try:
        parts = shlex.split(cmd or "")
    except ValueError:
        return None, []
    i = 0
    while i < len(parts) and parts[i].rsplit("/", 1)[-1] != tool:
        if parts[i].rsplit("/", 1)[-1] in _CMD_WRAPPERS or re.match(r"^\w+=", parts[i]):
            i += 1
            continue
        return None, []              # a non-wrapper precedes the tool -> not the primary command
    if i >= len(parts):
        return None, []
    i += 1                           # step past the tool token
    value_opts = _GLOBAL_VALUE_OPTS.get(tool, set())
    sub, args = None, []
    while i < len(parts):
        tok = parts[i]
        if tok in _SHELL_SEP:
            break
        if sub is None:
            if tok in value_opts:
                i += 2               # skip the global opt AND its value
                continue
            if tok.startswith("-"):
                i += 1               # valueless global flag / --opt=val form
                continue
            sub = tok
        else:
            args.append(tok)
        i += 1
    return sub, args


# --------------------------------------------------------------------------- #
# Git helpers  (clean-lift from the origin factory — pure git, no stack roots)
# --------------------------------------------------------------------------- #
def repo_root(path: str | None = None) -> str | None:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    if root and os.path.isdir(root):
        return root
    try:
        d = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
        out = subprocess.run(
            ["git", "-C", d, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        return out or None
    except Exception:
        return None


def _tracked(root: str, fp: str) -> bool:
    try:
        return subprocess.run(
            ["git", "-C", root, "ls-files", "--error-unmatch", fp],
            capture_output=True, text=True, timeout=5,
        ).returncode == 0
    except Exception:
        return False


def added_lines(root: str, fp: str):
    """[(lineno, text)] for lines this change ADDS vs HEAD (whole file if new)."""
    if not _tracked(root, fp):
        try:
            with open(fp, "r", errors="ignore") as f:
                return [(i + 1, ln.rstrip("\n")) for i, ln in enumerate(f) if ln.strip()]
        except Exception:
            return []
    try:
        out = subprocess.run(
            ["git", "-C", root, "diff", "-U0", "--no-color", "HEAD", "--", fp],
            capture_output=True, text=True, timeout=8,
        ).stdout
    except Exception:
        return []
    added, lineno = [], 0
    for ln in out.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", ln)
        if m:
            lineno = int(m.group(1))
            continue
        if ln.startswith("+") and not ln.startswith("+++"):
            added.append((lineno, ln[1:]))
            lineno += 1
        elif not ln.startswith("-"):
            lineno += 1
    return added


def staged_diff(root: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", root, "diff", "--cached", "--no-color"],
            capture_output=True, text=True, timeout=8,
        ).stdout
    except Exception:
        return ""


def git_out(root: str, *args) -> str:
    try:
        return subprocess.run(["git", "-C", root, *args],
                              capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""


def base_ref(root: str) -> str:
    """The integration ref this branch merges into, chosen offline by closest fork point.
    FACTORY_BASE_REF wins. Otherwise pick the candidate with the fewest commits to HEAD."""
    override = os.environ.get("FACTORY_BASE_REF")
    if override:
        candidates = [override]
    else:
        # honor the repo's configured base_branches (same source the push/branch gates use),
        # not a hardcoded main/staging — a repo whose integration branch is `develop` still resolves.
        bases = base_branches(root)
        candidates = [f"origin/{b}" for b in bases] + list(bases)
    best_ref, best_dist = "", None
    for ref in candidates:
        if not ref:
            continue
        mb = git_out(root, "merge-base", "HEAD", ref).strip()
        if not mb:
            continue
        try:
            dist = int(git_out(root, "rev-list", "--count", f"{mb}..HEAD").strip() or "0")
        except Exception:
            continue
        if best_dist is None or dist < best_dist:
            best_ref, best_dist = ref, dist
    return best_ref


def merge_base(root: str) -> str:
    ref = base_ref(root)
    return git_out(root, "merge-base", "HEAD", ref).strip() if ref else ""


def branch_touched_files(root: str):
    """Files changed on this branch vs base + uncommitted + staged."""
    names = set()
    base = merge_base(root)
    if base:
        names |= set(git_out(root, "diff", "--name-only", f"{base}...HEAD").split())
    names |= set(git_out(root, "diff", "--name-only").split())
    names |= set(git_out(root, "diff", "--cached", "--name-only").split())
    return {n for n in names if n}


def diff_hash_for(root: str, files) -> str:
    """A stable short hash of the current diff for a set of files (committed-on-branch +
    uncommitted). Shared by stop-completeness (freshness check) and stamp-ledger so a stamp
    made now matches what the gate computes at turn end."""
    import hashlib
    files = sorted(files)
    if not files:
        return ""
    base = merge_base(root)
    diff = ""
    if base:
        diff += git_out(root, "diff", f"{base}...HEAD", "--", *files)
    diff += git_out(root, "diff", "--", *files)
    return hashlib.sha1(diff.encode("utf-8", "ignore")).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Config loader  (zero-dep minimal YAML subset: flat key:value + one-level lists)
# --------------------------------------------------------------------------- #
def _strip_quotes(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def load_config(root: str | None = None) -> dict:
    """Parse factory.config.yaml from the WORKING repo root. Supports the subset the factory
    uses: `key: value` scalars and `key:` followed by `  - item` lists. No external dep."""
    root = work_root(root)
    path = os.path.join(root, "factory.config.yaml")
    cfg: dict = {}
    try:
        with open(path, "r", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return cfg
    cur_list_key = None
    for raw in lines:
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        # list item under the most recent `key:` with no inline value
        m = re.match(r"^\s+-\s+(.*)$", line)
        if m and cur_list_key is not None:
            cfg.setdefault(cur_list_key, [])
            if isinstance(cfg[cur_list_key], list):
                cfg[cur_list_key].append(_strip_quotes(m.group(1)))
            continue
        # top-level key
        m = re.match(r"^([A-Za-z0-9_\-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            # drop trailing inline comment on scalars
            if val and not val.startswith(("\"", "'")):
                val = val.split(" #", 1)[0].strip()
            if val == "":
                cur_list_key = key
                cfg.setdefault(key, [])
            elif val.startswith("[") and val.endswith("]"):
                # flow-style list: `packs: [ts-next]` / `base_branches: [main, staging]`
                cur_list_key = None
                inner = val[1:-1].strip()
                cfg[key] = [_strip_quotes(x.strip()) for x in inner.split(",") if x.strip()] if inner else []
            else:
                cur_list_key = None
                cfg[key] = _strip_quotes(val)
    return cfg


def work_root(root: str | None = None) -> str:
    """The repo being governed: explicit arg, else the working repo (CLAUDE_PROJECT_DIR/git),
    else FACTORY_HOME (dogfood/vendored fallback)."""
    return root or repo_root() or FACTORY_HOME


def detect_pack(root: str | None = None) -> list:
    """Sniff the working repo for a pack when no config declares one. Cheap marker checks."""
    r = work_root(root)
    try:
        if os.path.exists(os.path.join(r, "pubspec.yaml")):
            return ["flutter"]
        if os.path.exists(os.path.join(r, "package.json")):
            return ["ts-next"]
    except Exception:
        pass
    return []


def active_packs(root: str | None = None) -> list:
    """Packs declared in the working repo's config, else auto-detected from repo markers."""
    cfg = load_config(root)
    packs = cfg.get("packs")
    if isinstance(packs, list) and packs:
        return packs
    if isinstance(packs, str) and packs:
        return [packs]
    return detect_pack(root)


def factory_active(root: str | None = None) -> bool:
    """True if the working repo opts into the gates (has a factory.config.yaml)."""
    return os.path.exists(os.path.join(work_root(root), "factory.config.yaml"))


def pack_dir(name: str, root: str | None = None) -> str:
    """Packs always live in FACTORY_HOME — so a global install serves every working repo."""
    return os.path.join(FACTORY_HOME, "packs", name)


# --------------------------------------------------------------------------- #
# Conventions  (repo-level in factory.config.yaml; stack-level in the pack)
# --------------------------------------------------------------------------- #
def base_branches(root: str | None = None) -> list:
    """Branches that change only via PR. Repo-level (config); default main/staging."""
    v = load_config(root).get("base_branches")
    return v if isinstance(v, list) and v else ["main", "staging"]


def issue_pattern(root: str | None = None) -> str:
    """Regex an issue id must match in a PR body, or '' to disable the PR-link gate.
    Repo-level (config); default off — most repos don't require a tracker link."""
    v = load_config(root).get("issue_pattern")
    return v if isinstance(v, str) else ""


_CONV_CACHE: dict = {}

# Conventional-commit / branch types — the enforcement vocabulary, single source of truth here.
# Packs inherit these; a pack's conventions.json only needs `staged_block` (and may override branch/
# commit if its stack genuinely differs). Branch allows `hotfix`; commit does not (mirrors the hooks).
CORE_BRANCH_TYPES = ["feat", "fix", "chore", "refactor", "hotfix", "docs", "test", "perf", "ci", "build"]
CORE_COMMIT_TYPES = ["feat", "fix", "chore", "refactor", "docs", "test", "perf", "ci", "build"]


def pack_conventions(root: str | None = None) -> dict:
    """Branch/commit format + stack-specific staged-block patterns. branch/commit default to the
    CORE_* types and a pack overrides only if its conventions.json declares them (first pack that
    does wins). staged_block is concatenated across packs."""
    root = root or FACTORY_ROOT
    if root in _CONV_CACHE:
        return _CONV_CACHE[root]
    conv = {"branch": {"types": list(CORE_BRANCH_TYPES), "require_scope": True},
            "commit": {"types": list(CORE_COMMIT_TYPES)}, "staged_block": []}
    branch_set = commit_set = False
    for name in active_packs(root):
        path = os.path.join(pack_dir(name, root), "conventions.json")
        try:
            with open(path, "r", errors="ignore") as f:
                data = json.load(f)
        except Exception:
            continue
        if not branch_set and isinstance(data.get("branch"), dict):
            conv["branch"] = data["branch"]; branch_set = True
        if not commit_set and isinstance(data.get("commit"), dict):
            conv["commit"] = data["commit"]; commit_set = True
        conv["staged_block"] += data.get("staged_block", [])
    _CONV_CACHE[root] = conv
    return conv


# --------------------------------------------------------------------------- #
# Surface classifier  (mechanism in core; topology in the pack's surface.json)
# A surface map: {"ungoverned": [regex,...], "rules": [{match: surfaces:[...]}, ...]}
# match primitives: "contains" (substring), "endswith", "regex".
# --------------------------------------------------------------------------- #
_SURFACE_CACHE: dict = {}


def _norm(path: str) -> str:
    """Leading-slash form so relative and absolute paths match the same substrings."""
    return "/" + path.replace("\\", "/").lstrip("/")


def _compile_surface_data(data: dict) -> dict:
    """Compile a raw surface.json dict into {ungoverned:[regex], rules:[...]}"""
    ung = data.get("ungoverned", [])
    ung = ung if isinstance(ung, list) else [ung]
    compiled = []
    for p in ung:
        try:
            compiled.append(re.compile(p))
        except re.error as e:
            # a bad ungoverned pattern fails toward MORE coverage (safe-ish) but is still a
            # misconfig — surface it loudly rather than silently dropping the pattern.
            sys.stderr.write(f"factory: surface.json ungoverned pattern won't compile ({p!r}): {e}\n")
    return {"ungoverned": compiled, "rules": data.get("rules", [])}


def _load_pack_surface(pack: str, root: str | None = None) -> dict:
    path = os.path.join(pack_dir(pack, root), "surface.json")
    try:
        with open(path, "r", errors="ignore") as f:
            return _compile_surface_data(json.load(f))
    except Exception:
        return {"ungoverned": [], "rules": []}


def load_surface_map(root: str | None = None) -> dict:
    """The merged surface map of all ACTIVE packs (cached per root)."""
    root = root or FACTORY_ROOT
    if root in _SURFACE_CACHE:
        return _SURFACE_CACHE[root]
    ungoverned, rules = [], []
    for name in active_packs(root):
        m = _load_pack_surface(name, root)
        ungoverned += m["ungoverned"]
        rules += m["rules"]
    compiled = {"ungoverned": ungoverned, "rules": rules}
    _SURFACE_CACHE[root] = compiled
    return compiled


def _rule_matches(rule: dict, p: str) -> bool:
    if "contains" in rule and rule["contains"] in p:
        return True
    if "endswith" in rule and p.endswith(rule["endswith"]):
        return True
    if "regex" in rule:
        try:
            if re.search(rule["regex"], p):
                return True
        except re.error as e:
            # a bad ROUTING regex fails toward LESS coverage (a reviewer silently doesn't run) —
            # the dangerous direction. Make it loud so the misconfig can't hide as a clean run.
            sys.stderr.write(f"factory: surface.json rule regex won't compile ({rule.get('regex')!r}): {e}\n")
            return False
    return False


def _apply_surface_map(p: str, m: dict) -> set:
    """Apply a compiled surface map to a normalized path. Ungoverned -> empty set."""
    for rx in m["ungoverned"]:
        if rx.search(p):
            return set()
    s: set = set()
    for rule in m["rules"]:
        if _rule_matches(rule, p):
            for surf in rule.get("surfaces", []):
                s.add(surf)
    return s


def is_governed(path: str, root: str | None = None) -> bool:
    p = _norm(path)
    for rx in load_surface_map(root)["ungoverned"]:
        if rx.search(p):
            return False
    return True


def surface(path: str, root: str | None = None) -> set:
    """Surfaces a path belongs to, per the ACTIVE pack(s) merged map."""
    return _apply_surface_map(_norm(path), load_surface_map(root))


def surface_for_pack(path: str, pack: str, root: str | None = None) -> set:
    """Surfaces a path belongs to per a SPECIFIC pack's map — used to validate any pack
    independently of which pack is active. Zero core change to add a language."""
    return _apply_surface_map(_norm(path), _load_pack_surface(pack, root))


IS_TEST = lambda p: bool(
    re.search(r"(\.test\.|\.spec\.|_test\.|_spec\.|/__tests__/|/tests?/)", p.replace("\\", "/"))
)


# --------------------------------------------------------------------------- #
# Emit protocol
# --------------------------------------------------------------------------- #
def emit_block(reason: str) -> None:
    if warn_only():
        sys.stderr.write("⚠️  factory (warn-only, would block):\n" + reason + "\n")
        return
    print(json.dumps({"decision": "block", "reason": reason}))


def emit_warn(text: str) -> None:
    sys.stderr.write(text if text.endswith("\n") else text + "\n")


# --------------------------------------------------------------------------- #
# Fail-safe entrypoint
# --------------------------------------------------------------------------- #
def run(main_fn) -> None:
    if off():
        sys.exit(0)
    try:
        data = read_input()
        main_fn(data)
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)


# --------------------------------------------------------------------------- #
# Self-test
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    fails = 0

    def check(name, cond):
        nonlocal fails
        if not cond:
            fails += 1
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    # config loads + names at least one pack (pack-agnostic — works under any vendored config)
    check("config loads + names a pack", len(active_packs(FACTORY_ROOT)) >= 1)
    check("base_branches non-empty", len(base_branches(FACTORY_ROOT)) >= 1)
    conv = pack_conventions(FACTORY_ROOT)
    check("active pack defines branch types", bool(conv["branch"].get("types")))

    # surface MECHANISM, tested with a synthetic map (no dependence on the active pack)
    smap = _compile_surface_data({
        "ungoverned": ["/(node_modules|build|dist)/", "\\.gen\\.x$"],
        "rules": [
            {"contains": "/api/", "surfaces": ["api", "service"]},
            {"endswith": ".sql", "surfaces": ["db"]},
            {"regex": "/workflows?/", "surfaces": ["wf"]},
        ],
    })
    check("synthetic: /api/ -> api+service",
          _apply_surface_map(_norm("src/api/x.ts"), smap) == {"api", "service"})
    check("synthetic: .sql -> db", _apply_surface_map(_norm("m/001.sql"), smap) == {"db"})
    check("synthetic: /workflow/ regex -> wf",
          _apply_surface_map(_norm("a/workflow/y"), smap) == {"wf"})
    for dead in ["node_modules/x/y", "a/build/z", "dist/b.js", "p.gen.x"]:
        check(f"synthetic ungoverned: {dead} -> empty", _apply_surface_map(_norm(dead), smap) == set())

    # kill switch
    os.environ["FACTORY_OFF"] = "1"
    check("off() True when FACTORY_OFF=1", off() is True)
    os.environ["FACTORY_OFF"] = "0"
    check("off() False when FACTORY_OFF=0", off() is False)
    os.environ.pop("FACTORY_OFF", None)
    os.environ["FACTORY_WARN_ONLY"] = "1"
    check("warn_only() True when set", warn_only() is True)
    os.environ.pop("FACTORY_WARN_ONLY", None)

    # cli_subcommand: global flags must NOT hide the real subcommand from the gates
    check("git push plain", cli_subcommand("git push origin main", "git") == ("push", ["origin", "main"]))
    check("git -C dir push", cli_subcommand("git -C /x push origin main", "git")[0] == "push")
    check("git --no-pager commit", cli_subcommand("git --no-pager commit -m wip", "git")[0] == "commit")
    check("git -c k=v commit", cli_subcommand("git -c user.name=x commit -m wip", "git")[0] == "commit")
    check("git switch --create", cli_subcommand("git switch --create feat/x", "git") == ("switch", ["--create", "feat/x"]))
    check("gh -R o/r pr merge", cli_subcommand("gh -R o/r pr merge 1 --admin", "gh") == ("pr", ["merge", "1", "--admin"]))
    check("sudo prefix found", cli_subcommand("sudo git push origin main", "git")[0] == "push")
    check("VAR=val prefix found", cli_subcommand("GIT_TRACE=1 git push origin main", "git")[0] == "push")
    check("first-cmd-only (echo; git)", cli_subcommand("echo hi; git push origin main", "git") == (None, []))
    check("echo git push not a command", cli_subcommand("echo git push origin main", "git") == (None, []))
    check("tool absent -> None", cli_subcommand("ls -la", "git") == (None, []))

    # input parsing robustness
    check("tool_input({}) == {}", tool_input({}) == {})
    check("file_path({}) is None", file_path({}) is None)
    check("command({}) == ''", command({}) == "")
    check("file_path parses tool_input",
          file_path({"tool_input": {"file_path": "/x.ts"}}) == "/x.ts")

    print(f"\n_factory.py: {'ALL PASS' if fails == 0 else str(fails) + ' FAIL'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
