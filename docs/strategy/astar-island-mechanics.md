# Astar Island — Simulation Mechanics

## Overview

40×40 Norse world simulation running 50 years. Each year has 5 phases. The world is stochastic — same starting conditions produce different outcomes.

## Terrain Types

| Code | Terrain | Prediction Class | Behavior |
|------|---------|-----------------|----------|
| 10 | Ocean | 0 (Empty) | **Static** — never changes |
| 11 | Plains | 0 (Empty) | Dynamic — can become settlement, forest |
| 0 | Empty | 0 (Empty) | Static |
| 1 | Settlement | 1 | Dynamic — grows, fights, dies, becomes ruin/port |
| 2 | Port | 2 | Dynamic — coastal settlement with harbour |
| 3 | Ruin | 3 | Dynamic — can be reclaimed, overgrown, or fade |
| 4 | Forest | 4 | Semi-static — mostly stays, can be cleared near settlements |
| 5 | Mountain | 5 | **Static** — never changes |

## Annual Phases

```mermaid
flowchart LR
    A[Growth] --> B[Conflict]
    B --> C[Trade]
    C --> D[Winter]
    D --> E[Environment]
    E --> A
```

### 1. Growth Phase
- Settlements produce food from adjacent terrain (forests = food)
- Population grows when food is sufficient
- Prosperous settlements **expand** by founding new settlements on adjacent land
- Coastal settlements can develop into **ports** and build longships

### 2. Conflict Phase
- Settlements raid each other
- Longships extend raiding range significantly
- Desperate (low food) settlements raid more aggressively
- Raids loot resources and damage defenders
- Conquered settlements can **change faction**

### 3. Trade Phase
- Ports within range trade if not at war
- Trade generates wealth and food
- Technology diffuses between trading partners

### 4. Winter Phase
- All settlements lose food (varying severity)
- Settlements can **collapse** from starvation, sustained raids, or harsh winters
- Collapsed settlements become **Ruins**
- Population disperses to nearby friendly settlements

### 5. Environment Phase
- Nature reclaims abandoned land
- Nearby thriving settlements may **reclaim ruins** (new outpost)
- Coastal ruins can be restored as ports
- Unreclaimed ruins eventually become **forest** or **plains**

## Prediction Implications

### Static Cells (easy, high confidence)
- **Ocean**: 98% class 0 — never changes
- **Mountain**: 98% class 5 — never changes
- **Isolated forest** (far from settlements): 80% class 4

### Dynamic Cells (hard, need observations)
- **Settlements**: ~35% stay settlement, ~25% become ruin, ~10-25% become port (if coastal)
- **Plains near settlements**: ~25% become settlement (expansion), ~15% become forest
- **Forest near settlements**: ~50% stays, ~15% cleared for expansion
- **Ruins near settlements**: ~25% reclaimed, ~25% stay ruin
- **Isolated ruins**: ~30% become forest, ~25% stay ruin, ~25% become plains

### Adjacency Rules
- Cells within 2-3 tiles of settlements are MUCH more dynamic
- Coastal cells near settlements have port potential
- Forests adjacent to settlements provide food (less likely to be cleared)
- Isolated cells far from settlements tend toward static outcomes

## Query Strategy

With 50 queries across 5 seeds (10 per seed):

### v1 (current): Full coverage
- 9 queries per seed = 100% map coverage
- Each cell observed once → 90% confidence on observed class
- 5 remaining queries unused

### v2 (planned): Smart sampling
- Use initial grid for static cells (free, no queries)
- Focus queries on dynamic areas (near settlements)
- Multiple observations per area to build frequency distributions
- Same cell observed across different stochastic runs → empirical probability

### v3 (future): Simulation model
- Learn the hidden parameters from observations
- Build a local simulation approximation
- Run Monte Carlo simulations to generate ground-truth-like distributions
