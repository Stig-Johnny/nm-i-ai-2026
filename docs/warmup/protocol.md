# Game Protocol

## Connection

```
wss://game.ainm.no/ws?token=JWT
```

Token obtained via: `POST https://api.ainm.no/games/request` with `{"map_id": "UUID"}` and `Authorization: Bearer <access_token>`.

## Game State (Server → Client)

```json
{
  "type": "game_state",
  "round": 0,
  "max_rounds": 300,
  "score": 0,
  "drop_off": [1, 8],
  "grid": {
    "width": 12,
    "height": 10,
    "walls": [[0,0], [1,0], ...]
  },
  "bots": [
    {"id": 0, "position": [10, 8], "inventory": []}
  ],
  "items": [
    {"id": "item_0", "type": "cheese", "position": [3, 2]},
    {"id": "item_1", "type": "butter", "position": [5, 2]}
  ],
  "orders": [
    {
      "id": "order_0",
      "status": "active",
      "items_required": ["butter", "milk", "butter", "cheese"],
      "items_delivered": [],
      "complete": false
    },
    {
      "id": "order_1",
      "status": "preview",
      "items_required": ["cheese", "yogurt", "yogurt"],
      "items_delivered": [],
      "complete": false
    }
  ],
  "active_order_index": 0,
  "total_orders": 21,
  "status": null
}
```

## Actions (Client → Server)

```json
{
  "actions": [
    {"bot": 0, "action": "move_up"},
    {"bot": 1, "action": "pick_up", "item_id": "item_3"},
    {"bot": 2, "action": "drop_off"}
  ]
}
```

### Available Actions

| Action | Description |
|--------|-------------|
| `move_up` | Move bot up (y-1) |
| `move_down` | Move bot down (y+1) |
| `move_left` | Move bot left (x-1) |
| `move_right` | Move bot right (x+1) |
| `pick_up` | Pick up item (requires `item_id`, must be adjacent) |
| `drop_off` | Drop off inventory at drop-off zone |
| `wait` | Do nothing |

Invalid actions are treated as `wait`.

## Game Over

```json
{
  "type": "game_over",
  "score": 110,
  "items_delivered": 45,
  "orders_completed": 13,
  "rounds_used": 300
}
```

## Grid Layout (Easy, 12×10)

```
Row 0: ############ (wall border)
Row 1: #. . . . .# (open corridor)
Row 2: #.##c.b##y.m## (shelves at x=2,6,10; items at x=3,5,7,9)
Row 3: #.##y.m##c.b##
Row 4: #.##c.b##y.m##
Row 5: #. . . . .# (open corridor)
Row 6: #.##b.y##m.b##
Row 7: #. . . . .# (open corridor)
Row 8: #D. . . . .B# (drop-off at [1,8], bot spawn at [10,8])
Row 9: ############ (wall border)
```
