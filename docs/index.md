# NM i AI 2026

Norway's National AI Championship — March 19-22, 2026.

## Competition Status

**LIVE** — #12 overall with 49.8 points. ~42 hours remaining.

## The Four Tasks (25% each)

| Task | Type | Status | Score | Owner |
|------|------|--------|-------|-------|
| [Tripletex](tasks/task2.md) | AI accounting agent | Scoring, 6/30 task types | 47.6 | iClaw-E |
| [NorgesGruppen](tasks/task4.md) | Object detection | Scored! Training v4 overnight | 62.2 | Claude-5 |
| [Astar Island](tasks/task3.md) | Norse world prediction | Round 1+2 scored, poller for R3 | 39.6 | iClaw-E |
| Grocery Bot | Warm-up only | Not in overall score | N/A | — |

## Our Scores

| Task | Normalized Score |
|------|-----------------|
| Tripletex | 47.6 |
| NorgesGruppen | 62.2 |
| Astar Island | 39.6 |
| **Overall** | **49.8 (#12)** |

## Overnight (March 19-20)

- **v4 YOLOv8m training** running on MacBook MPS, ETA ~4 AM
- **v5 run.py** ready with conf=0.001 + torch.load patch
- **Astar poller** running on Mac Mini with crash-safe caching
- **Tripletex** rate limits reset at midnight — iClaw-E handling

## Team

- **Stig-Johnny** — human, account/submissions
- **Claude-5** — NorgesGruppen detection + infrastructure (MacBook)
- **iClaw-E** — Tripletex + Astar Island (Mac Mini M2)

## Links

- [Competition Platform](https://app.ainm.no)
- [Strategy](strategy/overview.md)
- [Competition Plan](strategy/competition-plan.md)
- [Coding Patterns](strategy/coding-patterns.md)
- [Astar Mechanics](strategy/astar-island-mechanics.md)
