# NM i AI 2026 — Competition Repo

## Git Rules

- **Each agent owns their task directory.** Only the owner pushes changes to that dir.
- Claude-5 and iClaw-E claim tasks via Discord at kickoff. Once claimed, only that agent touches `taskN/`.
- `shared/` — coordinate via Discord before editing. Pull before push.
- `docs/` — both agents update freely, but always pull first.
- Prefix commits: `task1:`, `task2:`, `task3:`, `shared:`, `docs:`
- Never force push.
- Always `git pull origin main --rebase` before pushing.
- If rebase conflicts: `git stash && git pull origin main --rebase && git stash pop`, resolve, then push.
- Small, frequent commits. Don't sit on uncommitted work.

## Docs Requirement

**Every code change MUST include a docs update.** When you:

- Add or change a task solution → update `docs/tasks/taskN.md` (approach, scores, status)
- Improve warm-up bot → update `docs/warmup/scores.md` with new scores
- Change strategy or approach → update `docs/strategy/overview.md`
- Add a new dependency → update `docs/strategy/coding-patterns.md`
- Discover something about the platform → update relevant doc

Docs auto-deploy to GitHub Pages on push. Keep them current so the whole team knows what's happening.

## Coding Standards

### Code Structure
- **One `solve()` function per task** — pure function, state in, action out. Keep logic here.
- **Separate concerns** — `solution.py` (entry point), `model.py` (inference), `utils.py` (helpers) if needed.
- **No premature abstraction** — duplicate code is fine. Don't build frameworks for one-off tasks.

### Performance
- **Profile before optimizing** — use `time.time()` around blocks to find bottlenecks.
- **Cache expensive computations** — model loading, pathfinding grids, parsed data.
- **Batch where possible** — one model call with 10 inputs beats 10 separate calls.

### Robustness
- **Handle unknown input gracefully** — always return something, never crash on unexpected data.
- **Default fallback answers** — if the model fails, return the most common class or a safe default.
- **Print on error, don't crash** — `try/except` around external calls only, print the error, return fallback.

### Speed Over Perfection
- **No type hints** during competition.
- **No docstrings** except module-level description.
- **No unit tests** — test by running against the platform.
- **Hardcode constants** — don't over-engineer config systems.
- **Copy-paste is fine** between tasks. Don't refactor during competition.

### What NOT to Do
- Don't install new frameworks mid-competition unless absolutely necessary.
- Don't rewrite working code that scores points — iterate on top of it.
- Don't spend more than 30 minutes stuck — ask for help on Discord or switch tasks.
- Don't optimize a task beyond 90% if another task is at 0%.

## LLM Access

We use **Claude Code subscription** — no API keys. For LLM tasks, reason directly or spawn sub-agents.

## Entry Point Pattern

Every task solution: `taskN/solution.py` with a `solve(state) -> action` pure function.

## Team

- **Claude-5** (MacBook) — primary coder
- **iClaw-E** (Mac Mini M2) — parallel executor
- **Stig** — human, platform access
