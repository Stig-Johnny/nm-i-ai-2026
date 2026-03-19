# NM i AI 2026 — Competition Repo

## Rules

- Push directly to main during competition (no PRs)
- Prefix commits: `task1:`, `task2:`, `task3:`, `shared:`, `docs:`
- Coordinate via Discord — call your task before touching it
- Never force push

## Docs Requirement

**Every code change MUST include a docs update.** When you:

- Add or change a task solution → update `docs/tasks/taskN.md` (approach, scores, status)
- Improve warm-up bot → update `docs/warmup/scores.md` with new scores
- Change strategy or approach → update `docs/strategy/overview.md`
- Add a new dependency → update `docs/strategy/coding-patterns.md`
- Discover something about the platform → update relevant doc

Docs auto-deploy to GitHub Pages on push. Keep them current so the whole team knows what's happening.

## LLM Access

We use **Claude Code subscription** — no API keys. For LLM tasks, reason directly or spawn sub-agents.

## Entry Point Pattern

Every task solution: `taskN/solution.py` with a `solve(state) -> action` pure function.

## Team

- **Claude-5** (MacBook) — primary coder
- **iClaw-E** (Mac Mini M2) — parallel executor
- **Stig** — human, platform access
