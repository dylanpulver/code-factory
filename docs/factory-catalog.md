# The Factory Catalog — what to build factories for

The code factory proved a **pattern**, not a tool: *arrive at an idea → say "ship it" → know it's
in good hands.* Trustworthy delegation of a whole pipeline, per output type. This doc is the map of
where that pattern could go — and the honest boundary of where it pays off.

> Sibling factories already exist: **code** (this repo, `ship-it`) and **research** (drives a sourced
> brief). This catalog is the dream space for the rest.

---

## The one law that predicts fit: verifiability of the *lit state*

The research is blunt: agentic factories pay off **where the output is automatically, deterministically
checkable** (tests, AST, render, load, reconcile). The corollary — *the medium is light*: code is inert
until run, a page until a user flows through it, a song until played. **A factory's `verify` step is
the lit state, not the artifact on the bench.**

So candidates sort onto a spectrum by "can a machine check the lit state?" — that's the whole triage.

---

## Three axes (a factory is `input → output @ lifecycle-stage`)

We instinctively list on the **output** axis, but there are three:

1. **Output** — code / landing page / song / report (what it makes)
2. **Lifecycle stage** — create / verify / **maintain / repair / evolve** (the under-explored axis;
   "keep it good" is endless toil and often higher-ROI than "make new")
3. **Input / trigger** — idea / transcript / alert / dataset (what fires it)

The richest factories combine axes: `alert → repaired service` (repair), `transcript → structured
issues` (create from a different input), `repo → patched deps` (maintain).

---

## Tier 1 — High verifiability (factories thrive — build these)

### Code-family (reuse the code-factory substrate — cheapest to spin up)
- **Code factory** ✅ built (ship-it)
- **Landing-page factory** — renders · CWV/Lighthouse · a11y · visual · copy/CTA
- **Web-app factory** — code checks + UX flows + design conformance
- **Mobile-app factory** — flutter pack + store/perf gates + screenshots
- **API / backend-service factory** — contract tests · load · schema · auth
- **Browser-extension factory** — loads · permissions audit · store-policy
- **CLI-tool factory** — runs · `--help` correct · exit codes · snapshots
- **Data-pipeline / ETL factory** — schema validates · row counts · idempotent
- **Dashboard / BI factory** — queries run · numbers reconcile · renders
- **IaC / infra factory** — `plan`/validate · policy check · dry-run
- **Integration / connector factory** — the API glue, contract-verified
- **Smart-contract factory** — tests + static-analysis audit (verifiable by design)
- **Email-template factory** — cross-client render is checkable

### Knowledge / research (verifiable via sources)
- **Research factory** ✅ built (sibling)
- **Competitive-analysis / vendor-landscape factory**
- **Due-diligence factory** — claims grounded, sourced
- **Docs factory** — docs match code (drift-checkable)
- **Changelog / release-notes factory** — derived from commits

### Data / analysis (verifiable via the numbers)
- **Eval / experiment factory** — the eval *is* the verify
- **Report / analysis factory** — query → analyze → verify → brief
- **Financial-model factory** — formulas check · sanity bounds · back-test
- **Bookkeeping / reconciliation factory** — debits=credits, verifiable

## Tier 2 — Medium verifiability (factory the structure; taste stays human)
High-frequency toil, criteria partly checkable:
- **Deck / pitch-deck factory** — structure + arc + design conformance
- **Doc / memo / proposal / RFP factory** — completeness, tone-rules as checks
- **PRD / product-spec factory** — acceptance criteria complete
- **Blog / article / SEO factory** — SEO auto-checkable, prose human
- **Newsletter factory** · **Course / curriculum factory** · **Resume / portfolio factory**
- **Ad-creative factory** — A/B testable → conversion is the verify (leans Tier 1)
- **Contract / legal-template factory** — clause-checklist verifiable, judgment human
- **Diagram / architecture factory** — renders, matches the system (drift-checkable)
- **Hiring factory** — JD → source → structured screen/eval
- **Sales-outreach factory** · **Support-response factory** (human-in-loop)

## Tier 3 — Low verifiability (factory the *spine* only — soul is human; here be dragons)
- **Song factory** — structure · stems · loudness/format · no-clipping ✅ ; "is it good" ❌
- **Image / art factory** — format/spec ✅ ; aesthetic ❌
- **Fiction / poem factory** — structure/consistency ✅ ; voice ❌
- **Video / podcast factory** — edit/format/loudness ✅ ; craft ❌

---

## The under-explored axis: lifecycle (maintain / repair / evolve)
Creation is a moment; keeping-good is forever, just as verifiable, arguably higher ROI:
- **Maintenance factory** — deps · security patches · docs-drift · dead-code · link-rot
- **Repair / incident factory** — alert → root-cause → fix → verify → postmortem
- **Upgrade / migration factory** — framework/API-version moves
- **Evolve / refactor factory** — pay down debt toward a target
- **Audit factory** — security / perf / dependency / accessibility sweeps → ranked report → fix-PRs

## Input-triggered factories (keyed by what fires them, not what they make)
- **Transcript factory** — meeting/voice-memo → decisions + actions + artifacts
- **Alert factory** — monitoring signal → triaged + repaired
- **Dataset factory** — raw data → cleaned + analyzed + reported
- **Inbox factory** — messages → triaged + drafted replies

---

## The bigger unit: composition (a production line of factories)
The dream isn't isolated factories — it's a **chain**, each node's output feeding the next:
```
idea → RESEARCH → PRD → CODE → VERIFY → DEPLOY → LANDING-PAGE → ANNOUNCE
```
"Idea → launched product" is a factory-of-factories. Say "ship it" once at the top; the line runs.

## The endpoint
- **A router** — "ship X" → dispatched to the right factory by output/trigger. One entry point.
- **A factory-factory** — mints a new factory from a spec, *after* Rule-of-Three reveals the shared
  core (code + research + one more = three). Then new output-types are config, not builds.

---

## How the dream fails (design around these — don't camp in them)
- **Over-abstract too early** — extract the framework at n=2 and you abstract the wrong thing. Wait for 3.
- **False-confidence checklists** — a low-verify factory (Tier 3) that *looks* rigorous but can't check
  what matters. Be honest about the lit state; don't fake the verify.
- **Maintenance recursion** — N factories are themselves things that rot; the fleet needs its own
  maintenance factory (or shared core, so there's one thing to maintain).
- **Focusing illusion** — not everything should be a factory. Genuinely one-off / taste-dominant work
  is overhead to factory-ize. Widen the frame before building.

---

## Where to start (fit × reuse × demand)
1. **Landing-page factory** — most-verifiable new output, reuses code substrate + design bits, real
   "say ship-it → get a deployed, fast, on-brand, converting page." The natural **third leg** →
   earns the right to extract the framework.
2. **Audit / maintenance factory** — highest lifecycle ROI, proven shape (a production audit sweep), pure reuse.
3. **Then** extract the factory-factory (post Rule-of-Three), and the rest become config.
