Pre-PR green light for the current branch.

Run the local checks and report. This is the fast gate before the review loop (`/ship-it` calls
it). Honors `FACTORY_OFF`.

## Steps

1. **Factory self-test** — the gates themselves must be green:
   ```bash
   factory selftest
   ```
2. **Pack check-matrix** — run each command in the active pack's `check.yaml` (skip a command if
   its tool isn't installed in this repo, and say so):
   ```bash
   cat "$(factory home)/packs/$(factory pack)/check.yaml"
   ```
   Typically: typecheck/analyze, lint, test. Run them, read failures, fix, re-run.
3. **Report** — a line per check: name → pass/fail (+ first failure if any). If everything green,
   the branch is clear for the review loop / PR. If not, fix and re-run before continuing.

Do not stamp anything on failure. Fix first, then re-run.
