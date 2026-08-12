# Running drives in parallel

Ship several independent things at once without code/git collisions. **No factory feature is
needed for this** — the harness already provides the isolation. This doc is the convention.

## How it works

Run each drive as its own **isolated agent**. The harness gives each one a fresh git worktree
(Agent tool `isolation: "worktree"`, or a Workflow fan-out with `agent(..., {isolation: 'worktree'})`).
That means per-drive: its own working dir, its own branch, its own index. Collisions on code/git
are **impossible** — not "managed", impossible.

```
parallel( tasks.map(t => () =>
  agent(`Drive this task through ship-it: ${t}`, { isolation: 'worktree' })
))
```

## The one thing the harness leaves to you: deps

A fresh worktree has **no `node_modules`** (or `.dart_tool`, etc.). So the first thing a drive does
in its worktree is provision deps — the command is declared per pack in `check.yaml`:

```yaml
install: pnpm install        # ts-next
install: flutter pub get     # flutter
```

The drive runs that once after landing in the worktree, then proceeds (build → review → verify → PR).

## Where parallelism stops (be honest about this)

Worktrees isolate **code**, not **runtime resources**. Parallel drives still share:
- the **database**, **Redis**, **ports** (`next dev` :3000), external API rate limits, shared `.env`.

So parallel is safe **through build → review → unit-verify (V0–V2) → PR** for *independent* tasks.
It is **not** safe for V3/integration (hitting a shared DB/port) or for tasks that touch *overlapping*
files (those defer the collision to merge time). Don't run parallel integration against one dev DB
without per-drive resource isolation — that's a separate, deeper problem.

## Cleanup

The harness auto-removes a worktree **if unchanged**. A drive that commits leaves a worktree +
branch — `git worktree remove <path>` after the PR is open, and `git worktree prune` to clear any
stale ones from crashed drives.

## When to build more

Only when an actual parallel run surfaces actual friction (deps flow, verify-in-worktree,
cleanup). Don't pre-build — the filesystem isolation is the easy part and the harness already has it.
