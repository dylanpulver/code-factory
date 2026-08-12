# Eval & Calibration Strategy — how we verify the factory actually works

The factory's quality is currently **asserted, not verified**: reviewers ship golden Bad/Good
fixtures and standards ship regexes, but nothing proves they catch real violations without
crying wolf. This doc is the grounded plan to close that — what the field does (cited), and the
tiered build that applies it here. **Tiers 0–1 are built (structural `fleet-selftest` + the
`eval-patterns` regex eval); Tiers 2–3 are still the map.**

> Provenance: synthesized from a web-research sweep (2024–2026), 20 sources (18 primary arXiv +
> Google's SWE book + 3 practitioner blogs). The research harness's *adversarial verify* phase
> failed on API rate-limiting (every vote errored → false "refuted" verdict), so these are
> **sourced but not independently re-verified by the harness**. Cross-checked against sources I
> can vouch for (Tricorder/SWE-book ch20, CriticBench, RealCritic). Re-run verify when convenient.

---

## 0. The key insight — our architecture is already the validated shape

The SAST+LLM adjudication pattern (arXiv 2510.02534) is *exactly* what we built: a cheap,
high-recall **deterministic gate** (CodeQL/SAST ≈ our regex `standards-check`) feeding an **LLM
adjudication layer** that filters false positives (≈ our reviewer fleet). On that combo, frontier
models reach **~0.98 precision, F1 0.91–0.96**. The two-layer design isn't a guess — it's SOTA.

**Gap:** we don't yet *wire the adjudication step*. Today the regex BLOCKs directly. The upgrade
(see §4.4): route ambiguous regex hits through a cheap LLM confirm/dismiss before surfacing.

---

## 1. The eval trap we must avoid (why naive eval is worthless)

Testing a reviewer against **its own** Bad/Good fixtures is **circular** — same author wrote the
rule and the example, so passing proves nothing (overfit by construction; the "great in
demo, bad on real input" failure). The field avoids this by separating who-generates from
who-grades and using held-out, externally-sourced gold sets:

- **CriticBench** — compiles 15 *existing external* datasets as the critic's fixtures.
- **CodeCriticBench** — separates the data-generation models from the 38 evaluated critic models;
  grounds scores in a 20% **manually-annotated held-out** gold set.
- **SAST+LLM (2510.02534)** — labels derived from *external patch verification* (CVE fixes), not
  by re-running the analyzer on its own output.

**Our non-circular source of truth:** the calibration loop (§4.3) harvests real findings + your
accept/dismiss verdicts. Externally-sourced by construction; grows representative over time.

---

## 2. Precision-first — the spine (Google Tricorder)

Tricorder is the gold standard for "static analysis at scale that developers don't disable."

- **"Effective false positive" is defined by developer *action*, not technical correctness** — a
  warning is a FP if the developer took no positive action, *even if technically correct*. This
  is the metric. It maps directly onto our accept/dismiss signal.
- **Ship gate: a new analyzer must clear <10% effective-FP** (devs feel it's right ≥90% of the
  time). Overall prod rate kept **<5%** across 100+ analyzers.
- **Calibration at scale:** harvests "Please Fix" / "Not useful" clicks as the feedback loop.
- Practitioner consensus (multi-tool PR bake-offs): **false positives cause alert fatigue → the
  whole tool gets ignored.** Optimize **precision over recall**: a missed bug is cheaper than a
  dismissed reviewer.

**Policy we adopt:** a `BLOCK`-tier rule must clear **<10% effective-FP** or it's downgraded to
`WARN`. Everything uncertain ships as `WARN`. (Gives our existing "BLOCK = near-zero-FP" an actual
number.)

---

## 3. LLM-as-judge biases (our reviewers ARE LLM judges)

- **Self-preference bias** — judges overrate their *own* output (GPT-4 worst, ~0.52 on an
  equal-opportunity metric; arXiv 2410.21819). **Risk for us:** in `ship-it`, Claude writes the
  code *and* reviews it. Mitigate: review with a fresh instance / different model than generated
  the change; frame the reviewer adversarially.
- **Verbosity & position bias** — verbosity dropped a judge ~15pp; position swung ~30pp (arXiv
  2604.16790). Position is low-risk for us (we flag findings on one diff, not A/B compare).
- **Test-retest instability** — weak models scored ~coin-flip consistency. We use Opus (good), but
  *measure it*: run a reviewer twice on the same diff, check verdict stability; flag flaky ones.
- **Single-judge style injection** — one judge imprints its style/policy. Mitigated by our
  **diverse-lens panel** (code-quality / security / observability / test-quality).
- **Verdict accuracy overstates quality** — 55% correct verdicts but 68% of critiques still
  low-quality (RealCritic 2501.14492). Don't grade a reviewer by "flagged the bad fixture."
  **Closed-loop metric:** grade by whether *acting on* the finding improved the code.
- **Even SOTA critics ~75% accuracy** (o1-preview, CodeCriticBench). Keep human-in-loop; reviewers
  are assistants, not oracles. **Fine-grained checklist** critique tracks humans better than
  binary — our P1/P2/P3 + `file:line` + fix is already the right shape.

---

## 4. The tiered build (rigor where it's cheap; care where it's hard)

| Tier | What | Cost | Real? |
|---|---|---|---|
| **0 structural** (have it) | fleet-selftest: opus, read-only, fixtures present, no orphans | free | rot-only |
| **1 pattern fixtures** | held-out pass/block *lines* for the regexes, authored independently | cheap | fully real (deterministic, no LLM, no subjectivity) |
| **2 calibration loop** | log findings + accept/dismiss → effective-FP per rule/reviewer; auto-demote over the bar | moderate | real by construction |
| **3 LLM eval** | run reviewers on the *harvested* set; measure precision + consistency | higher | real once Tier 2 has data |

### 4.1 Precision policy (cheap, first)
Codify the Tricorder bar in the pack-authoring contract (reviewer README + standards): `BLOCK` ⇒
<10% effective-FP or downgrade to `WARN`.

### 4.2 Tier-1 pattern fixtures
Per pack, a `patterns/standards.tests.json`: lines that **should** block and lines that **should
not**, written independently of the regexes. A `factory eval-patterns` runs them, reports
precision/recall on the deterministic gates. Non-circular as long as fixtures aren't derived from
the regex. Rigor is free here.

### 4.3 Tier-2 calibration loop (the prize)
Log every surfaced finding + your **accept / dismiss / no-action** verdict to a local ledger.
Compute **effective-FP rate per rule and per reviewer** (action-based, à la Tricorder). Auto-demote
a rule `BLOCK → WARN → off` when it exceeds the bar; flag a reviewer whose dismiss-rate is high.
This *is* the harvested, externally-sourced golden set — feeds Tier 3.

### 4.4 LLM adjudication step (architectural upgrade)
Route ambiguous `WARN`-tier regex hits through a cheap reviewer (confirm/dismiss) before surfacing
— the SAST+LLM pattern (~0.98 precision). Cuts FP without losing the regex's recall.

### 4.5 Closed-loop metric (later, the honest one)
Grade findings by whether acting improved the code, not verdict-match. Hard; do when Tier 2 has
real data.

---

## 5. Deliberately deferred (don't cargo-cult the origin factory)
The **QA-until-green loop** and **deploy/tracker adapters** — a large production monorepo needs them; personal repos may
not. The review loop + gates likely suffice for solo work. Add only when a real repo demands it.

---

## 6. Sources
- LLM-as-judge biases & SE judging: arXiv 2604.16790, 2410.21819, 2402.13764
- Critic/judge benchmarks (non-circular): CriticBench (2402.14809 + repo), CodeCriticBench
  (2502.16614), RealCritic (2501.14492)
- SAST + LLM adjudication: arXiv 2510.02534
- Static analysis at scale / effective-FP / precision gate: Google SWE book ch.20 (Tricorder),
  abseil.io/resources/swe-book/html/ch20.html
- Precision vs recall in AI review / alert fatigue: augmentcode deep-code-review guide; dev.to
  4-tool 146-PR bake-off
