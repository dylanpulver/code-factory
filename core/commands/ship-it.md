End-to-end factory run. Input: $ARGUMENTS (a description or an issue id)

The orchestrator. Chains the pipeline and **auto-dispatches** review off the diff of the repo
you're currently in. Works from any repo (the engine is global; this classifies the current
repo's diff). Honors `FACTORY_OFF` / `FACTORY_WARN_ONLY`.

## Sequence

0. **Read the repo profile** — what the factory already knows about THIS repo (so you don't
   re-derive it): `factory profile show` (`.factory/profile.md` — Map, Toolchain, Idioms,
   Hotspots, Findings). Use it to locate code + match the repo's patterns. **Verify on use:** a
   profile claim is a hint, not gospel — confirm it still holds (grep the symbol/path) before
   relying on it; fix a stale entry as you go. If there's no profile, `factory profile init`.
1. **Build** — implement against the request with small conventional commits.
2. **/factory-check** — local green light (factory selftest + the pack check-matrix). Fix red first.
3. **Dispatch** — compute the reviewer set deterministically off the current repo's diff:
   ```bash
   factory dispatch
   ```
   This classifies each changed file with the pack's surface map and prints
   `{ files, surfaces, reviewers, qa }`. (No config in this repo? `factory dispatch` auto-detects
   the pack from repo markers.)
4. **Review loop (the keystone) — auto-dispatch → fix → re-review, bounded ~3 rounds:**
   - **If this change edited the fleet itself, re-calibrate first (auto, no remembering):**
     ```bash
     factory eval-reviewers --changed    # did this branch touch a reviewer prompt / regression set?
     ```
     If it reports a change, run the seeded behavioral eval (spawn each reviewer on its
     `regression.json` cases, record `flag|clean` per case to a verdicts JSON), then:
     ```bash
     python3 "$(factory home)/core/fleet/eval-reviewers.py" --score <verdicts.json> --record
     ```
     It records the scoreboard to the trend and **alerts if catch-rate dropped / FP rose** vs the
     last run — so editing a reviewer can't silently regress it. (Objective: the bugs are planted.)
   - For each name in `reviewers`, spawn an Agent **in parallel**. The reviewer's prompt is the
     body of its file in the active pack:
     ```bash
     cat "$(factory home)/packs/<pack>/reviewers/<name>-reviewer.md"
     ```
     Pass that as the agent's instructions, plus the diff + the changed files to read in full.
     (In a repo where `factory init` registered agents under `.claude/agents/`, you may instead
     use `subagent_type: "<name>-reviewer"`.)
   - Collect findings. **Act on what they find — don't just report it:** apply surviving P1/P2
     fixes as small commits.
   - Re-run only the reviewers whose surface you touched. Loop until no P1/P2 survives, bounded
     to ~3 rounds; escalate anything still open to the human with specifics.
   - **Log the run (free telemetry — the reviewers already ran, so this costs no tokens).** After
     the loop settles, record one record per dispatched reviewer so the empirical loop accumulates
     without anyone remembering to run anything:
     ```bash
     echo '[{"reviewer":"security","surface":"api","fired":true,"findings":["missing authz on mutating handler"],"outcome":"fixed"},
            {"reviewer":"data-access","surface":"api","fired":false}]' \
       | python3 "$(factory home)/core/fleet/log-review.py"
     ```
     `outcome` for a fired finding: `fixed` (you applied it — real value), `dismissed` (false alarm
     you rejected — real-world noise), or `waived` (deferred). A reviewer that flagged nothing is
     `"fired": false`. Feeds `review-rollup`.
5. **Verify (prove it works — don't ship on "looks right")** — the output must be *shown* to work,
   not just reviewed. Climb the ladder as far as the change allows:
   - **Write a test that proves THIS change** — fails-before / passes-after against the task's
     acceptance criteria. (For a clear-criteria task, write it *first* and build until green.)
     A test that can't fail proves nothing — make it exercise the new behavior.
   - Run the prover (it builds a base worktree and checks the fail→pass transition + V0 lint + V1
     suite, then stamps the ledger):
     ```bash
     factory verify --test <path/to/the/new/test>
     ```
   - **Route the new test through the test-quality reviewer** (catch a vacuous/flaky test).
   - If the change isn't meaningfully testable (config/docs/pure refactor), say so and waive
     explicitly (`stamp-ledger.py verify waived "reason"`) — verify is a gate, not a wall.
   - Record the **rung reached** (V0/V1/V2) in the report — that's the trust signal.
   - `factory verify` writes `.claude/state/verify-evidence.md` (rung, check table, the
     fail-before/pass-after proof, and any V3 exercise output).
6. **Report + PR** — phase-by-phase: dispatched reviewers, rounds run, findings fixed, **verify
   rung reached**, escalations. **Open the PR with the verify evidence in the body** — append the
   contents of `.claude/state/verify-evidence.md` so the reviewer sees the proof without re-running:
   ```bash
   gh pr create --title "..." --body "$(cat pr-body.md; echo; cat .claude/state/verify-evidence.md)"
   ```
7. **Grow the profile** — append anything this drive had to *figure out* that the next one
   shouldn't re-derive: a repo idiom you learned (`factory profile add Idioms "auth: ..."`), a
   real finding (`... add Findings "..."`), a decision (`... add Decisions "..."`), a hotspot.
   This is the memory half — every drive makes the next one sharper on this repo.

**The review + verify are loops, not checkpoints.** Steps 4–5 run, read results, fix, and
re-validate on their own (bounded, then escalate). Pause only when a bounded loop exhausts or for
a genuinely human-only decision. Don't open the PR until verify reaches V1+ (or an explicit waiver).

## Later phases (not yet built — see docs/PLAN.md)

- Tracker adapter (scope/start/close) · deploy adapter (push-to-main | pr-to-main |
  staging-then-main | manual). (V3 exercise + V4 evidence ARE built — steps 5–6 above use them.)
