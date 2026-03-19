# Score History

## Best Scores

| Map | Score | Items | Orders | Version |
|-----|-------|-------|--------|---------|
| Easy | 126 | 51 | 15 | v3 (approach-cell opt) |
| Medium | 101 | - | - | v2 (per-bot planner) |
| Hard | 113 | 48 | 13 | v4 (fleet coordination) |
| Expert | 42 | 22 | 4 | v2 |
| Nightmare | — | — | — | untested |

## Version History

### v4 — Fleet coordination (Hard: 113)
- Fleet-wide demand coordination
- Deliver early if drop-off closer than nearest needed item
- Deadlock recovery: try any unblocked direction instead of wait
- Regression: Easy dropped from 126 → 110

### v3 — Approach-cell optimization (Easy: 126)
- Pre-computed best approach cell adjacent to items
- Nearest item of ANY wanted type, not just highest-priority
- Restored preview pre-fetch (1 slot max)

### v2 — Per-bot planner (Easy: 118)
- Per-bot state machine: pick → deliver → repeat
- Only deliver when inventory matches active order
- A* pathfinding, items treated as impassable

### v1 — Initial (Easy: 110)
- BFS pathfinding
- Item bundling (pick 3 before drop-off)
- Adjacent pickup discovery

## Leaderboard (Pre-competition, ended March 16)

| Team | Easy | Notes |
|------|------|-------|
| PH | 127 | Leader |
| QuantumPulse | 126 | |
| Us | 126 | |
