# Competition Strategy

## The Math That Drives Everything

Scoring formula: **average of 3 normalized task scores (0-100 each)**.

This has critical implications:

| Scenario | Task 1 | Task 2 | Task 3 | Overall |
|----------|--------|--------|--------|---------|
| Perfect on 2, skip 1 | 100 | 100 | 0 | **66.7** |
| Decent on all 3 | 70 | 70 | 70 | **70.0** |
| Great on 2, weak on 1 | 90 | 90 | 30 | **70.0** |

**Conclusion:** A weak score on a skipped task is catastrophic. Breadth beats depth.

## Phase Plan

### Phase 1: First Blood (Hours 0-3)

**Goal:** Submit a working solution for ALL 3 tasks. Any score > 0.

| Time | Action |
|------|--------|
| 18:15 | Docs drop — iClaw-E scrapes all 3 task specs, posts to Discord |
| 18:15-18:30 | Read specs, identify submission format for each task |
| 18:30-19:00 | Ship naive baselines for all 3 tasks |
| 19:00-19:15 | Verify all 3 tasks have scores on leaderboard |

**Why this matters:** If one task has a hard submission format or unexpected API, we discover it NOW, not at hour 40.

### Phase 2: Low-Hanging Fruit (Hours 3-12)

**Goal:** Get each task to ~50-70% of theoretical max with known techniques.

- Identify which task has the most score headroom per hour of work
- Apply standard approaches (pre-trained models, API calls, ensemble methods)
- Focus effort where marginal improvement is highest

### Phase 3: Optimization Sprint (Hours 12-48)

**Goal:** Push scores from 70% to 85%+ on each task.

- Fine-tune approaches based on what the leaderboard shows is possible
- A/B test different strategies within rate limits
- Monitor other teams' scores to gauge theoretical ceiling

### Phase 4: Final Push (Hours 48-69)

**Goal:** Squeeze out final points, ensure code repo is clean.

- Focus on the task where we're furthest from the leader
- Clean up code for public repo submission (required for prizes)
- Submit repo URL before deadline
- No risky changes in last 2 hours

## Team Roles

### Claude-5 (Primary Coder)

- Reads task docs, designs solution architecture
- Implements core algorithms
- Runs games via automated pipeline (CDP → API → WebSocket)
- Coordinates with iClaw-E via Discord
- Manages git repo and code quality

### iClaw-E (Parallel Executor)

- Scrapes docs the instant they drop
- Handles one full task independently (likely LLM task)
- Runs research and competitive analysis in background
- Tests alternative approaches on assigned task
- Pushes code to feature branches for review

### Stig (Human Operator)

- Platform account and Vipps verification (done)
- Manual platform interactions if automation fails
- Final approval on submissions
- Submits public repo URL before deadline

## Technical Stack

### Compute

| Resource | Specs | Best For |
|----------|-------|----------|
| MacBook (Claude-5) | Apple Silicon, no GPU | Code, API calls, light inference |
| Mac Mini M2 (iClaw-E) | Apple Silicon, no GPU | Parallel tasks, browser automation |

### No GPU Strategy

We have zero GPU access. Every approach must be:

1. **API-based** — Claude Haiku (fast, cheap), OpenAI GPT-4o-mini
2. **CPU-optimized** — ONNX Runtime, quantized models, sklearn/XGBoost
3. **Pre-trained** — No fine-tuning, use zero-shot or few-shot

### Expected Task Approaches

| Task Type | Primary Approach | Fallback |
|-----------|-----------------|----------|
| **Computer Vision** | CLIP zero-shot / EfficientNet-B0 ONNX | Claude vision API (slower, costs $) |
| **Language Model** | Claude Haiku API (3ms latency) | Local small LLM via llama.cpp |
| **Machine Learning** | XGBoost + Optuna auto-tuning | sklearn ensemble (RF + GBM + LR) |
| **WebSocket Game** | A* + Hungarian assignment (from warm-up) | BFS greedy |
| **Optimization** | scipy.optimize / OR-tools | Greedy heuristic |
| **Data Processing** | pandas + numpy | Raw Python |

## Automation Pipeline

Proven during warm-up. Ready for main competition:

```
Chrome (logged in) → CDP cookie extraction → API token request → WebSocket game → Bot
```

- `warmup/run_game.py` — one-command game runner
- Token acquisition: ~2s
- Game cooldown: 60s between games
- Can run games unattended

## Competitive Intelligence

### What We Know From Warm-up

- Top team (PH) scored 127 on Easy — only 1 point above our 126
- The platform uses WebSocket + JSON for all challenges
- MCP server available at `mcp-docs.ainm.no/mcp` for docs
- Rate limits are enforced server-side (60s cooldown confirmed)

### What to Watch At Kickoff

1. **Submission format** — is it WebSocket (like warm-up), file upload, or API call?
2. **Rate limits** — how many submissions per hour?
3. **Evaluation** — real-time scoring or batch?
4. **Data access** — do we get training data, or is it zero-shot?

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Task requires GPU training | Can't compete on that task | Use API-based approach, accept lower score |
| Platform goes down | Lost time | Build locally, submit when back |
| Rate limit too restrictive | Can't iterate fast enough | Get it right the first time, test locally |
| One task is completely foreign | 0 on one task = max 66.7 overall | Research first, at least submit something |
| iClaw-E goes offline | Lose parallel capacity | Claude-5 handles all 3 sequentially |
| Auth token expires | Can't submit | Stig re-logs in, or use magic link |

## Key Principles

1. **Ship first, optimize later** — A working 30-point solution beats an unfinished 90-point solution
2. **All 3 tasks matter equally** — Never abandon a task
3. **Automate everything** — Manual steps waste time at 3 AM
4. **Trust the leaderboard** — If top score is 50, don't chase 100
5. **Communicate** — Post scores and blockers to Discord immediately
