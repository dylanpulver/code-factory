# Building factories with research (the method)

How to build a new factory cheaply. The insight: **don't hand-author a factory's standards —
generate them.** Use the research factory (already built) to build the next factories. The factory
that drives research feeds the factories that drive everything else.

## Every factory = fixed spine + variable content

A factory encodes the **spine** (the steps you always do), not the content. ship-it drives infinite
different code changes through one pipeline; a landing-page factory drives infinite different pages
through one pipeline (`create → domain → Vercel + DNS → design → verify → ship`). The variation
lives in the *inputs to one step* (the design), not the pipeline. So "this output type is too broad"
is a non-problem — you're encoding 5 steps, not every artifact.

## The content is a research brief, not prose you write

A factory's judgment layer — its reviewers, its standards, its verify bars — is exactly the kind of
thing the research factory produces: best practices, grounded in sources, decision-ready. So:

1. **Research the output type** → `research` run on "best practices for <output>" (structure,
   quality criteria, the machine-checkable bars — e.g. for landing pages: hero/CTA/section
   conventions, conversion heuristics, CWV/a11y/perf thresholds).
2. **The brief becomes the pack** → its findings map straight onto the pack's `reviewers/`,
   `patterns/`, and the verify `check.yaml` (the lit-state bars).
3. **Build around the code-factory spine** → reuse the engine (dispatch, verify ladder, profile,
   gates); only the pack + the verify step are new.
4. **Dogfood + grow the profile** → real runs sharpen it; catches feed the ratchet.

## Why this is lazy and compounding

- No inventing best-practices from memory — generate, ground, cite.
- The research factory pays for itself twice: once as a tool, again as the factory-builder.
- Each new factory reuses the spine; only the content differs. Naming the recurring
  problem-context-solution (Gang of Four) makes it buildable-upon, not reinvented each time.

## The guardrail

Only works where the lit state is machine-checkable — research can find the bars, but if the domain
has no checkable bars (Tier 3: song/art), the brief has nothing to become. Research the fit first;
if there's no verify, there's no factory.

Do NOT extract a shared "factory framework" from this yet — wait for the third leg (Rule of Three).
This method is how you build leg 3, not a reason to abstract at n=2.
