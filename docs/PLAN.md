# code-factory — Strategy & Plan

A portable, language-agnostic **coding quality-enforcement factory**. Extracted from a
production monorepo's `.claude/` factory, generalized so the engine ships once and every
project plugs in a config — no per-language fork.

> Status: **P0–P5 COMPLETE.** All four enforcement layers built, three packs (ts-next +
> flutter + node-zerodep), 17 selftest modules green, dogfooded, pushed. Transplant proven: adding
> a pack required zero stack-specific core logic. This doc is the map; the build followed it.

---

## 1. Vision

One **core** (stack-agnostic engine) + swappable **packs** (per-language/stack content) +
thin **adapters** (tracker, deploy). A new project = pick a pack, declare a config. A new
language = author a pack, never fork the engine.

```
factory = core (lift once) + pack (author per stack) + adapters (thin, optional, default-off)
```

The origin factory bolts engine + content into one `.claude/`. This repo splits them so the
engine is reusable across every repo (and every language).

---

## 2. The reusable heart (why this is worth extracting)

The keystone is the `ship-it` orchestrator. Its value is **not** the 11 steps — it's **two
bounded auto-loops**, both driven by the same trio:

- **review-until-clean** — `surface()` classify diff → `dispatch-matrix` → spawn matched
  reviewers (parallel) → apply surviving P1/P2 fixes → re-review. Bounded ~3 rounds, then
  escalate.
- **QA-until-green** — validate → discover → fix → re-validate → stamp ledger only on real
  pass. Bounded per surface, then escalate.

The trio that powers both: **`surface()` classifier + `dispatch-matrix.json` + ledger
stamping**. That trio is language-agnostic — it's git + harness orchestration; it never reads
a `.ts`. Everything tracker/infra/QA-command-specific is **replaceable endpoints** hanging
off it.

---

## 3. The transplant sort

Every component of the origin factory was run through a transplant-survival test — lifted into
a new repo, does it survive with roots, or tear off as embedded dependency?

| Bucket | Meaning | Lands in |
|---|---|---|
| **clean-lift** | zero stack roots, copy as-is | `core/` |
| **parameterize** | logic portable, content is stack-specific → pull content to a pack | `core/` (engine) + `packs/` (content) |
| **leave-behind** | embedded infra dependency | re-implemented as a thin adapter, default-off |

### What lands where

**core/ (language-agnostic):**
- `_factory.py` — fail-safe `run()`, kill-switch (`FACTORY_OFF`/`WARN_ONLY`), stdin-JSON
  parsing, git helpers (`added_lines`/`staged_diff`/`base_ref`), `emit_block`/`emit_warn`.
  **Change from the origin: surface map is NOT hardcoded here — it's loaded from config.**
- `hooks/` — git-safety engines (branch/commit/push/merge/pr-create/dangerous-cmd), the
  `standards-check` engine (consumes pattern packs), stop/completeness gates, `stamp-ledger`.
- `fleet/` — dispatch loader, reviewer template, `fleet-selftest`.
- `selftest.sh` — the whole suite.

**packs/<stack>/ (authored per stack):**
- `surface.json` — path → surface-name map (the topology) + `ungoverned` patterns
- `patterns/` — BLOCK/WARN regex packs for `standards-check` (+ `standards.tests.json` fixtures)
- `reviewers/` — the Opus reviewer prompts + `dispatch-matrix.json`
- `conventions.json` — branch/commit format + stack-specific staged-block patterns
- `check.yaml` — the check-matrix commands (`tsc`/`lint`/`test`)

**adapters/ (thin, optional, default-off):**
- `tracker/` — scope/start/close. Varies wildly per project (some have no scoping source).
  Default off. Linear adapter is the first real one (see §7 open decisions).
- `deploy/` — declared strategy: `push-to-main` | `pr-to-main` | `staging-then-main` |
  `manual`. Default `manual`. Reuses the base-ref auto-detect.

---

## 4. The seam (the single most important design move)

The origin factory hardcodes the surface map *inside* `_factory.py` — a smeared responsibility
(shotgun-surgery smell). The whole extraction hinges on **inverting that dependency**:

> Core stops knowing the topology. It loads `factory.config.yaml` from repo root, which names
> the active pack(s) + adapters. The pack declares surfaces, patterns, reviewers, checks. Core
> is a stack-agnostic engine; the config + pack are the only authored-per-project artifacts.

Seam contract — core reads, never hardcodes:
- which pack(s) are active
- the surface map (from the pack)
- the pattern packs (from the pack)
- the reviewer set + dispatch matrix (from the pack)
- the check-matrix commands (from the pack)
- the tracker + deploy adapter choices (from config, default-off/manual)

**Graceful degradation:** missing config/pack → core no-ops or warns, never crashes
(fail-safe invariant, exit 0).

---

## 5. Repo layout

```
code-factory/
  core/                  language-agnostic engine
    _factory.py          config-driven; no hardcoded paths
    hooks/               block layer (git-safety + standards engine + stop gates)
    fleet/               judge layer (dispatch loader + reviewer template + selftest)
    selftest.sh
  packs/
    ts-next/             FIRST pack — extracted from the origin monorepo (TS / Next / Hono / Prisma)
      surface.json
      patterns/           (+ standards.tests.json)
      reviewers/  (+ dispatch-matrix.json)
      conventions.json
      check.yaml
    (flutter/ node-zerodep/ ... additive)
  adapters/
    tracker/             scope/start/close — default off
    deploy/              push-to-main | pr-to-main | staging-then-main | manual
  docs/
    PLAN.md              this file
    handbook.md          day-to-day usage (later)
  factory.config.yaml    picks pack(s) + adapters; dogfoods the seam
```

The repo **dogfoods itself** — its own commits/PRs run through its own gates via its own
`factory.config.yaml`.

---

## 6. Safety invariants (never violate — carried over from the origin factory)

1. **Fail-safe** — wrap `main` with `run`; any error exits 0.
2. **Added-lines-only** — edit gates inspect added lines, never the whole file.
3. **Precision tiers** — BLOCK only near-zero-false-positive; everything else WARN.
4. **Escape clause** — every block message tells the model how to proceed on a true FP.
5. **Offline + fast** — no network; git + regex only.
6. **Self-test** — every hook supports `--selftest` (block + pass + fail-safe cases).

---

## 7. Phases (walking-skeleton — prove the keystone first)

- **P0 — skeleton (prove the review loop).** core `_factory.py` reading config + `surface()`
  from a pack + `dispatch-matrix` + ONE generic reviewer + a stub `ship-it` that runs the
  bounded review loop end-to-end + `selftest.sh` green. *Proves the seam + the keystone loop.*
- **P1 — git-safety pack.** branch/commit/push/merge/pr-create/dangerous-cmd, config-driven.
- **P2 — standards engine.** `standards-check` with pattern-pack loading + a ts-next starter pack.
- **P3 — fleet.** dispatch loader + generic reviewers (code-quality, test-quality, security,
  observability) + `fleet-selftest` + agent template.
- **P4 — completeness/ledger/stop gates + handbook.**
- **P5 — second-repo / second-pack proof.** Drop config into a real second repo (or author
  a second pack). The true transplant test.

## 8. Inversion check (run before declaring core clean)

Grep `core/` for leaked roots — any hit = push to a pack/adapter:
`apps/`, `packages/`, the origin repo's name, `Temporal`, `Prisma`, `Hono`, `Linear`, `GCP`,
hardcoded `staging`/`main`.

---

## 8.5. Eval & calibration (next major thread)

The factory's quality is asserted, not verified. The grounded plan to fix that — cited SOTA
(Tricorder precision-first, SAST+LLM adjudication, non-circular gold sets, LLM-judge bias
controls) + a tiered build (pattern fixtures → calibration loop → LLM eval) — lives in
[`eval-strategy.md`](eval-strategy.md). Build when ready; rigor-sensitive, don't rush.

## 9. Open decisions (parked, not blocking)

- **Tracker master workspace** — one master tracker (e.g. Linear) with teams/initiatives/projects
  for personal repos. The tracker adapter would target it. Separate track; doesn't block core.
- **Pack naming/versioning** — semver packs? Later.
- **Distribution** — decided: standalone private repo, vendored-copy into big repos when
  needed. No submodule/package/symlink mechanism built.

---

## 10. Lenses used (provenance)

- **transplant-survival** — the sort function (clean-lift / parameterize / leave-behind).
- **continuity / invisible seam** — core reads a config contract, never knows the repo's name.
- **shotgun-surgery → missing module boundary** — surface map smeared in `_factory.py` → localize to config.
- **nesting** — language packs nest *inside* one core, not side-by-side ports.
- **walking-skeleton** — prove the review loop end-to-end before breadth.
- **inversion** — list every way core stays coupled, design each out (§8).
- **graceful-degradation** — missing config → no-op/warn, never crash.
