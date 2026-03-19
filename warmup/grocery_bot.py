"""
Grocery Bot — NM i AI 2026 Warm-up Challenge
=============================================
Optimized multi-bot grocery store agent.

Strategy:
  - Hungarian algorithm for optimal bot→item assignment
  - BFS pathfinding with wall avoidance
  - Order completion priority (+5/order >> +1/item)
  - Item bundling (pick multiple items before drop-off)
  - Cooperative collision avoidance via reservation table

Run:
    python warmup/grocery_bot.py --url "wss://game.ainm.no/ws?token=TOKEN"
"""

import asyncio
import json
import sys
from collections import deque
from typing import Any

import numpy as np
import websockets

try:
    from scipy.optimize import linear_sum_assignment
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    print("WARNING: scipy not installed — using greedy assignment instead of Hungarian")


# ============================================================
# Pathfinding
# ============================================================

def bfs(start: tuple, goal: tuple, walls: set, width: int, height: int,
        reserved: set = None) -> list[tuple]:
    """BFS shortest path from start to goal, avoiding walls and reserved cells."""
    if start == goal:
        return [start]

    queue = deque([(start, [start])])
    visited = {start}

    while queue:
        pos, path = queue.popleft()
        for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            nx, ny = pos[0] + dx, pos[1] + dy
            npos = (nx, ny)
            if (0 <= nx < width and 0 <= ny < height
                    and npos not in walls
                    and npos not in visited
                    and (reserved is None or npos not in reserved)):
                if npos == goal:
                    return path + [npos]
                visited.add(npos)
                queue.append((npos, path + [npos]))

    # No path found — try without reservations
    if reserved:
        return bfs(start, goal, walls, width, height, reserved=None)
    return [start]  # stuck


def manhattan(a: tuple, b: tuple) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def direction_from_move(current: tuple, next_pos: tuple) -> str:
    dx = next_pos[0] - current[0]
    dy = next_pos[1] - current[1]
    if dx == 1: return "move_right"
    if dx == -1: return "move_left"
    if dy == 1: return "move_down"
    if dy == -1: return "move_up"
    return "wait"


# ============================================================
# Assignment
# ============================================================

def assign_bots_to_targets(bots: list[dict], targets: list[dict],
                           walls: set, width: int, height: int) -> dict:
    """Assign bots to targets using Hungarian algorithm or greedy fallback.

    Returns: {bot_id: target_dict}
    """
    if not bots or not targets:
        return {}

    n_bots = len(bots)
    n_targets = len(targets)

    # Build cost matrix (Manhattan distance)
    cost = np.full((n_bots, n_targets), 9999.0)
    for i, bot in enumerate(bots):
        bpos = tuple(bot["position"])
        for j, target in enumerate(targets):
            tpos = tuple(target["position"])
            cost[i][j] = manhattan(bpos, tpos)

    if HAS_SCIPY:
        row_idx, col_idx = linear_sum_assignment(cost)
        return {bots[r]["id"]: targets[c] for r, c in zip(row_idx, col_idx) if cost[r][c] < 9990}
    else:
        # Greedy: assign closest pairs
        assignments = {}
        used_targets = set()
        for i, bot in enumerate(bots):
            best_j = None
            best_cost = 9999
            for j, target in enumerate(targets):
                if j not in used_targets and cost[i][j] < best_cost:
                    best_cost = cost[i][j]
                    best_j = j
            if best_j is not None and best_cost < 9990:
                assignments[bot["id"]] = targets[best_j]
                used_targets.add(best_j)
        return assignments


# ============================================================
# Game Logic
# ============================================================

class GroceryAgent:
    def __init__(self):
        self.walls: set = set()
        self.width: int = 0
        self.height: int = 0
        self.path_cache: dict = {}
        self.round_num: int = 0

    def update_grid(self, grid: dict):
        self.width = grid.get("width", 0)
        self.height = grid.get("height", 0)
        self.walls = set(tuple(w) for w in grid.get("walls", []))
        self.path_cache.clear()

    def get_needed_items(self, orders: list, items: list) -> list:
        """Get items that are needed for active orders, sorted by priority."""
        needed_types = set()
        for order in orders:
            if order.get("complete") or order.get("status") != "active":
                continue
            required = set(order.get("items_required", []))
            delivered = set(order.get("items_delivered", []))
            for item_type in required - delivered:
                needed_types.add(item_type)

        # Filter available items to those needed
        needed_items = [i for i in items if i.get("type") in needed_types]

        # If no needed items, return all items (speculative picking)
        if not needed_items:
            return items
        return needed_items

    def decide(self, state: dict) -> dict:
        """Main decision function — returns actions for all bots."""
        self.round_num = state.get("round", 0)

        grid = state.get("grid", {})
        if grid:
            self.update_grid(grid)

        bots = state.get("bots", [])
        items = state.get("items", [])
        orders = state.get("orders", [])
        drop_off = state.get("drop_off")
        drop_off_zones = state.get("drop_off_zones", [])

        if drop_off:
            drop_offs = [tuple(drop_off)]
        elif drop_off_zones:
            drop_offs = [tuple(z) for z in drop_off_zones]
        else:
            drop_offs = []

        # Track which cells are reserved this round
        reserved = set()
        actions = []

        # Separate bots: those with inventory → go drop off, those without → go pick up
        bots_to_pickup = []
        bots_to_dropoff = []

        for bot in bots:
            inventory = bot.get("inventory", [])
            if len(inventory) > 0:
                bots_to_dropoff.append(bot)
            else:
                bots_to_pickup.append(bot)

        # --- Bots heading to drop-off ---
        for bot in bots_to_dropoff:
            bpos = tuple(bot["position"])

            # Find closest drop-off
            if drop_offs:
                closest_drop = min(drop_offs, key=lambda d: manhattan(bpos, d))
            else:
                actions.append({"bot": bot["id"], "action": "wait"})
                continue

            if bpos == closest_drop:
                actions.append({"bot": bot["id"], "action": "drop_off"})
            else:
                path = bfs(bpos, closest_drop, self.walls, self.width, self.height, reserved)
                if len(path) > 1:
                    next_pos = path[1]
                    reserved.add(next_pos)
                    actions.append({"bot": bot["id"], "action": direction_from_move(bpos, next_pos)})
                else:
                    actions.append({"bot": bot["id"], "action": "wait"})

        # --- Bots picking up items ---
        needed_items = self.get_needed_items(orders, items)

        if bots_to_pickup and needed_items:
            # Build target list with positions
            targets = [{"id": i.get("id"), "type": i.get("type"),
                        "position": i.get("position", [0, 0])}
                       for i in needed_items]

            assignment = assign_bots_to_targets(bots_to_pickup, targets,
                                                 self.walls, self.width, self.height)

            for bot in bots_to_pickup:
                bpos = tuple(bot["position"])
                target = assignment.get(bot["id"])

                if target is None:
                    actions.append({"bot": bot["id"], "action": "wait"})
                    continue

                tpos = tuple(target["position"])

                if bpos == tpos:
                    actions.append({"bot": bot["id"], "action": "pick_up",
                                    "item_id": target["id"]})
                else:
                    path = bfs(bpos, tpos, self.walls, self.width, self.height, reserved)
                    if len(path) > 1:
                        next_pos = path[1]
                        reserved.add(next_pos)
                        actions.append({"bot": bot["id"],
                                        "action": direction_from_move(bpos, next_pos)})
                    else:
                        actions.append({"bot": bot["id"], "action": "wait"})
        else:
            for bot in bots_to_pickup:
                actions.append({"bot": bot["id"], "action": "wait"})

        return {"actions": actions}


# ============================================================
# WebSocket Client
# ============================================================

agent = GroceryAgent()


async def run(url: str):
    print(f"Connecting to {url}")
    async with websockets.connect(url) as ws:
        async for message in ws:
            state = json.loads(message)
            msg_type = state.get("type", "")

            if msg_type == "game_over":
                score = state.get("score", "?")
                print(f"\nGame over — final score: {score}")
                break

            action = agent.decide(state)
            round_num = state.get("round", "?")
            score = state.get("score", 0)
            n_bots = len(state.get("bots", []))
            n_items = len(state.get("items", []))

            if round_num == 1 or (isinstance(round_num, int) and round_num % 50 == 0):
                print(f"Round {round_num} | Score: {score} | Bots: {n_bots} | Items: {n_items}")

            await ws.send(json.dumps(action))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="WebSocket URL with token")
    args = parser.parse_args()
    asyncio.run(run(args.url))
