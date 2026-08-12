# Review fleet — shared contract

The reviewers the factory's review loop dispatches. **All `model: opus`, all read-only.**
Dispatch is computed from the diff via `core/fleet/dispatch.py` reading `dispatch-matrix.json`,
and consumed by the `ship-it` command's bounded review-until-clean loop.

Reviewers are pack content — a different stack ships a different fleet. The dispatch + selftest
mechanism is stack-agnostic core; only these prompts + the matrix are pack-specific.

## Every reviewer follows this contract

- **Frontmatter:** `name`, one-line `description` (its trigger surface), `tools: Read, Grep,
  Glob, Bash` (read-only — a reviewer never mutates code), `model: opus`.
- **Inputs (from the dispatcher):** the diff, the changed-file list, the pack's standards, the
  repo profile (`.factory/profile.md` — Map/Idioms/Findings for this repo), and any requirements
  the orchestrator synthesized.
- **Grounding:** read surrounding code (not just diff lines) before asserting; verify any
  symbol/path a rule names still exists (kills the staleness class).
- **Output:** findings as **P1/P2/P3**, each with `file:line`, a one-paragraph rationale tied to
  a standard, and a copy-paste fix for P1/P2; grouped by file; first-instance-detailed then
  "same as …". No style nits (the formatter owns those).
- **Severity:** P1 = bug / data-corruption / security / missing requirement (blocks merge) ·
  P2 = logic gap / edge case / missed reuse (should fix) · P3 = elegance / clarity / pre-existing.
- **Fail-open:** a reviewer never blocks the loop; the hard gates are the hooks.

## Golden fixtures (anti-rot)

Each reviewer ends with a `## Golden fixtures` section: a `### Bad (must flag)` and a
`### Good (must pass)` fenced block, co-located with the checklist that judges them.
`core/fleet/fleet-selftest.py` asserts every reviewer is `opus` + read-only, ships both
fixtures, and that the reviewer set and `dispatch-matrix.json` are mutually consistent (no
orphan reviewer). Whether a reviewer actually catches its bad fixture is an eval-time check; the
self-test guarantees the structure can't silently rot.

## The fleet (ts-next, current)

code-quality · test-quality · security · observability

Adding a reviewer: drop `<name>-reviewer.md` here (contract above + Bad/Good fixtures), wire it
into `dispatch-matrix.json` (`always` or a surface), and `fleet-selftest.py` must stay green.
