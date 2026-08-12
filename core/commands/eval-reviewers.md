Run the real-catch regression set against the reviewer fleet (the behavioral ratchet).

For the active pack, load `reviewers/regression.json` (held-out real-catch cases) and verify the
fleet still behaves — bugs stay caught, fixes stay un-flagged. Run periodically and after any
reviewer-prompt change. Costs tokens (spawns reviewers); not in the deterministic suite.

## Steps

1. **Structural guard first** (free, deterministic):
   ```bash
   factory eval-reviewers        # validates the set + prints coverage
   ```
2. **Behavioral run (rigor: k-runs + objective catch + different-model judge).** For each case:
   - Spawn the named reviewer (prompt = body of
     `$(factory home)/packs/<pack>/reviewers/<reviewer>-reviewer.md`) on the case's `code` in a
     **fresh agent**, and **run each case k=3 times** (independent agents) — LLM reviewers are
     unstable run-to-run, so one pass is noise; take the **majority** verdict.
   - Decide each run's verdict **objectively, not by vibes**:
     - **flag case** → `"flag"` iff the reviewer raises a P1/P2 whose finding references the case's
       `catch_signal` concept (it named the *actual planted bug*, not something adjacent). Make this
       match call with a **different model (Haiku — not the Opus reviewer/drive)**: self-preference
       bias is real and doesn't shrink with capability, so nothing may grade itself.
     - **clean case** → `"flag"` iff the reviewer raises ANY P1/P2 (a false alarm on known-good
       code); else `"clean"`.
   - Majority across the k runs → one `{case_name: "flag"|"clean"}` entry. The *verdict* needs no
     judge (ground truth is planted); only the narrow *catch-signal match* uses the Haiku judge.
3. **Score** — feed the verdicts to the deterministic scorer:
   ```bash
   python3 "$(factory home)/core/fleet/eval-reviewers.py" --score <verdicts.json>
   ```
   It prints per-reviewer **catch-rate** (recall on planted bugs) and **FP-rate** (false alarms on
   clean code) — the two numbers the empirical loop lives on. Read it opinionated: a reviewer whose
   FP-rate exceeds its catch-rate is **noisier than useful** (prune it or tier it to a cheaper
   model); a reviewer with no clean case has an **unmeasured FP blind spot** — add one. Track the
   scoreboard over time; that trend is what tells you if the fleet is real or theater.

## Rules
- These cases are **held-out** — never edit a reviewer to pass a specific case by name; fix the
  reviewer's general reasoning. Tuning to the set destroys it (golden-set rule).
- A genuine real bug the fleet catches in the wild (like a `/ship-it` find you accepted) should be
  **added** to `regression.json` as a new `flag` case (+ its fix as a `clean` case). The set grows
  from real use; that's the ratchet.
