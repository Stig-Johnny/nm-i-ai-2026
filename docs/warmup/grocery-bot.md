# Grocery Bot

Pre-competition warm-up challenge. Connect an AI agent via WebSocket to control worker bots in a grocery store simulation.

## Difficulty Levels

| Level | Grid | Bots | Rounds | Drop Zones |
|-------|------|------|--------|------------|
| Easy | 12×10 | 1 | 300 | 1 |
| Medium | 16×12 | 3 | 300 | 1 |
| Hard | 22×14 | 5 | 300 | 1 |
| Expert | 28×18 | 10 | 300 | 1 |
| Nightmare | 30×18 | 20 | 500 | 3 |

## Scoring

- **+1** per item delivered
- **+5** per completed order
- Only best score per map retained on leaderboard

## Map UUIDs

```
easy       3c7e90e6-e4bc-4095-a42b-e04eb6738809
medium     0aba093f-a942-4a65-88ed-c60eb50b1c4a
hard       9bb9b3de-7a56-4d5e-a4d4-637b08a526c8
expert     c6acd676-ece3-4be5-ae24-9aff9e78f475
nightmare  8e5eeedd-767e-465d-94a4-67aef1b5b0d1
```

## Key Discoveries

1. **Items block movement** — bots cannot walk through item cells
2. **Pick up requires adjacency** — Manhattan distance == 1
3. **drop_off only removes items matching active order** — extras stay in inventory forever
4. **Shelves are infinite** — same item_id reappears after pickup
5. **Items on floor cells, not walls** — but BFS must treat them as impassable

## Running

```bash
# Automated (requires Chrome with CDP on port 9222)
python warmup/run_game.py easy

# Manual
python warmup/grocery_bot.py --url "wss://game.ainm.no/ws?token=TOKEN"
```
