# NM i AI 2026

Norway's National AI Championship — March 19-22, 2026.

## Competition Status

**LIVE** — Competition started March 19 at 18:00 CET. ~66 hours remaining.

## The Four Tasks (25% each)

| Task | Type | Submission | Status | Owner |
|------|------|-----------|--------|-------|
| [Grocery Bot](tasks/task1.md) | Real-time navigation | WebSocket agent | Scoring | Shared |
| [Tripletex](tasks/task2.md) | AI accounting agent | HTTPS endpoint | Rank #1, score 0.29 | iClaw-E |
| [Astar Island](tasks/task3.md) | Norse world prediction | REST API | Round 1 submitted, awaiting score | Claude-5 |
| [NorgesGruppen](tasks/task4.md) | Object detection | ZIP upload | Training, submit at midnight | Claude-5 |

## Current Scores

### Grocery Bot

| Map | Bots | Best Score |
|-----|------|-----------|
| Easy | 1 | 110 |
| Medium | 3 | **117** |
| Hard | 5 | 113 |
| Expert | 10 | 13 |
| Nightmare | 20 | — |

### Tripletex

**Rank #1**, score 0.29, 1/24 task types. Agent running via Cloudflare tunnel, working on GCP Cloud Run deploy for full proxy access.

### Astar Island

Round 1 submitted (all 5 seeds, 100% coverage). Awaiting score — round closes ~21:42 CET. Poller running for Round 2.

### NorgesGruppen

Training YOLOv8n single-class detector on 248 images. Detection-only scores up to 70%. Submit at midnight UTC when rate limit resets.

## Team

- **Stig-Johnny** — human, account/submissions, platform access
- **Claude-5** — AI agent, primary coder + strategy (MacBook)
- **iClaw-E** — AI agent, parallel executor (Mac Mini M2)

## Links

- [Competition Platform](https://app.ainm.no)
- [Docs](https://app.ainm.no/docs)
- [Repo](https://github.com/Stig-Johnny/nm-i-ai-2026)
- [Strategy](strategy/overview.md)
- [Coding Patterns](strategy/coding-patterns.md)
