# code-factory

A portable, language-agnostic **coding factory** for Claude Code. It drives a change end to end —
and **builds, reviews, proves, and remembers**, so what ships is correct, not just plausible.

One **core** engine (git + harness orchestration) + swappable **packs** (per-language/stack
content). The engine never reads your source language — only the packs do, so adding a language is
a pack, not a fork.

```
factory = core (lift once) + pack (author per stack)
```

## What it does

| | |
|---|---|
| **Build** | drives a single-issue change with small conventional commits |
| **Review** | dispatches matched Opus reviewers off the diff (security, data-access, api-contract, migration-safety, observability, test/code-quality…), bounded fix loop |
| **Prove** | the **verify ladder** — V0 typecheck/lint → V1 tests → V2 fail-before/pass-after → V3 exercise the real path → V4 evidence on the PR. *Differential*: only blocks on regressions the change introduced, not pre-existing debt |
| **Remember** | a per-repo **profile** (sniffed Map + Toolchain, grown Idioms/Findings, verified-on-use) so it doesn't re-derive the codebase every drive |
| **Gate** | fail-safe hooks: branch/commit/push/merge/PR + dangerous-cmd + a real-time standards edit-gate + an opt-in verify Stop-gate |
| **Not rot** | everything self-tests; reviewers carry golden fixtures; the **ratchet** keeps real catches caught |

Two enforcement strengths back it: **hooks** (hard, harness-run) and **reviewers** (Opus judgment,
auto-dispatched). Dogfooded on production Next.js and FinTech codebases; surfaced 5 P1s in its
first audits.

## Status

**Working and dogfood-proven.** 17 self-test modules green; the repo gates its own commits. Two
packs: `ts-next` (deep — 7 reviewers, standards, regression set) and `flutter`. Full design + the
build history in [`docs/PLAN.md`](docs/PLAN.md); the verify rationale in
[`docs/eval-strategy.md`](docs/eval-strategy.md).

## Use it (global — the daily driver)

Install once. The engine stays in this checkout; nothing is copied into your repos (same model as
`~/.claude/skills`).

```bash
./install-global.sh          # /ship-it + /factory-check in every repo; `factory` CLI on PATH
```

Then, in any repo you want gated:

```bash
cd ~/code/your-app
factory init                 # auto-detects the pack, drops config + hook wiring -> global engine
factory profile init         # sniff this repo's real structure + toolchain (optional but recommended)
```

Now in that repo:
- **Gates fire automatically** — bad branch/commit/push, `--admin` merge, `rm -rf /`, edits adding
  `as any`/secrets/`console.log`-in-service → blocked or warned live.
- **`/factory-check`** — local green light (factory selftest + the pack's check-matrix).
- **`/ship-it`** — the keystone: reads the repo profile → builds → dispatches reviewers (bounded fix
  loop) → **verifies** (proves the change works) → opens the PR with the verify evidence attached.

Commands are global; the **gates** fire only where you ran `factory init`. Everything else (and any
repo with its own `ship-it`, which wins by precedence) stays untouched.

## Use it (vendored — self-contained, e.g. for CI)

```bash
./install.sh /path/to/your-repo ts-next     # copies core/ + pack + config + wiring into the repo
```

Embeds the engine (no global dependency). Verify with `bash core/selftest.sh`.

## `factory` CLI

```
factory init [pack]            opt this repo into the gates (config + hook wiring -> engine)
factory profile init|show|add  what the factory knows about THIS repo (Map/Toolchain/Idioms/Findings)
factory dispatch               classify the current diff -> which reviewers/QA
factory verify [--test <path>] prove the change works (V0–V4)
factory eval-patterns          run the standards fixtures (precision/recall per rule)
factory eval-reviewers         the real-catch regression set (coverage + structural guard)
factory new-reviewer <pack> <name>   scaffold a verified reviewer
factory pack | packs | home    active pack · available packs · install location
```

## Layout

| Dir | What |
|---|---|
| `core/` | language-agnostic engine — `_factory.py`, `hooks/`, `fleet/` (dispatch, verify, profile, eval), `commands/`, `bin/factory` |
| `packs/ts-next/`, `packs/flutter/` | per-stack content — `surface.json`, `conventions.json`, `patterns/`, `reviewers/`, `check.yaml`, fixtures |
| `factory.config.yaml` | picks pack(s) + policy (`base_branches`, `issue_pattern`, `require_verify`) |
| `docs/` | `PLAN.md` (strategy + history), `eval-strategy.md`, `parallel-drives.md` |

## Run drives in parallel

Ship several independent things at once: run each as its own isolated agent — the harness gives each
a fresh worktree, so collisions are impossible. See [`docs/parallel-drives.md`](docs/parallel-drives.md)
(no factory feature needed; just a convention + the pack's `install` command).

## Add a language

Author `packs/<stack>/` (surface map, conventions, standards patterns, reviewers, `check.yaml`).
No core change — `core/` never reads your source language. `factory new-reviewer` scaffolds a verified
reviewer; `bash core/selftest.sh` must stay green.
