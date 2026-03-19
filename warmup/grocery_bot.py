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

def bfs(start: tuple, goal: tuple, blocked: set, width: int, height: int,
        reserved: set = None) -> list[tuple]:
    """BFS shortest path from start to goal, avoiding blocked cells and reserved cells.

    The goal cell itself is allowed even if in blocked set (for adjacency-based pickup,
    we path to an adjacent cell instead).
    """
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
                    and npos not in visited
                    and (npos not in blocked or npos == goal)
                    and (reserved is None or npos not in reserved)):
                if npos == goal:
                    return path + [npos]
                visited.add(npos)
                queue.append((npos, path + [npos]))

    # No path found — try without reservations
    if reserved:
        return bfs(start, goal, blocked, width, height, reserved=None)
    return [start]  # stuck


def bfs_to_adjacent(start: tuple, target: tuple, blocked: set, width: int, height: int,
                    reserved: set = None) -> list[tuple]:
    """BFS to a cell adjacent to target (for picking up items on shelves/walls)."""
    # Find walkable cells adjacent to target
    adj_cells = []
    for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
        nx, ny = target[0] + dx, target[1] + dy
        npos = (nx, ny)
        if (0 <= nx < width and 0 <= ny < height and npos not in blocked):
            adj_cells.append(npos)

    if not adj_cells:
        return [start]

    # If already adjacent, done
    if start in adj_cells:
        return [start]

    # BFS to closest adjacent cell
    best_path = None
    for adj in adj_cells:
        path = bfs(start, adj, blocked, width, height, reserved)
        if len(path) > 1 or path[0] == adj:
            if best_path is None or len(path) < len(best_path):
                best_path = path

    return best_path if best_path else [start]


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
        self.round_num: int = 0

    def update_grid(self, grid: dict):
        self.width = grid.get("width", 0)
        self.height = grid.get("height", 0)
        self.walls = set(tuple(w) for w in grid.get("walls", []))

    def get_blocked(self, items: list, bot_positions: set) -> set:
        """Build full blocked set: walls + item positions + other bot positions."""
        blocked = set(self.walls)
        for item in items:
            blocked.add(tuple(item.get("position", [0, 0])))
        blocked |= bot_positions
        return blocked

    def get_needed_items(self, orders: list, items: list, bot_inventories: dict) -> list:
        """Get items needed for active+preview orders, accounting for what bots already carry."""
        from collections import Counter
        needed_counts = {}
        # Include active AND preview orders so bots pre-fetch for next order
        for order in orders:
            if order.get("complete"):
                continue
            status = order.get("status")
            if status not in ("active", "preview"):
                continue
            required = order.get("items_required", [])
            delivered = order.get("items_delivered", [])
            req_counts = Counter(required)
            del_counts = Counter(delivered)
            for item_type, count in req_counts.items():
                remaining = count - del_counts.get(item_type, 0)
                if remaining > 0:
                    needed_counts[item_type] = needed_counts.get(item_type, 0) + remaining

        # Subtract items already in bot inventories
        for bot_id, inv in bot_inventories.items():
            for item_type in inv:
                if item_type in needed_counts:
                    needed_counts[item_type] = max(0, needed_counts[item_type] - 1)

        # Filter items to those still needed
        needed_items = []
        type_taken = {}
        for item in items:
            itype = item.get("type")
            if itype in needed_counts and needed_counts[itype] > type_taken.get(itype, 0):
                needed_items.append(item)
                type_taken[itype] = type_taken.get(itype, 0) + 1

        return needed_items

    def _active_order(self, orders: list):
        return next((o for o in orders if o.get("status") == "active" and not o.get("complete")), None)

    def _inv_useful(self, order, inventory: list) -> int:
        """Count items in inventory that can be delivered to this order right now."""
        if not order:
            return 0
        needed = list(order.get("items_required", []))
        for d in order.get("items_delivered", []):
            if d in needed:
                needed.remove(d)
        count = 0
        inv = list(inventory)
        for t in needed:
            if t in inv:
                count += 1
                inv.remove(t)
        return count

    def is_adjacent(self, pos: tuple, target: tuple) -> bool:
        return manhattan(pos, target) == 1

    def _to_pick(self, active, preview, inventory: list) -> list:
        """Types still needed — active first, preview fills spare slots. Never over-picks."""
        inv = list(inventory)
        result = []

        if active:
            needed = list(active.get("items_required", []))
            for d in active.get("items_delivered", []):
                if d in needed: needed.remove(d)
            for t in needed:
                if t in inv:
                    inv.remove(t)
                else:
                    result.append(t)

        slots_left = 3 - len(inventory) - len(result)
        if preview and slots_left > 0:
            needed = list(preview.get("items_required", []))
            for d in preview.get("items_delivered", []):
                if d in needed: needed.remove(d)
            for t in needed:
                if slots_left <= 0: break
                if t in inv:
                    inv.remove(t)
                else:
                    result.append(t)
                    slots_left -= 1

        return result

    def _plan_bot(self, bot, state, blocked, assigned_ids, reserved):
        """Plan one bot. Returns action dict."""
        bid  = bot["id"]
        pos  = tuple(bot["position"])
        inv  = list(bot["inventory"])

        orders = state.get("orders", [])
        items  = state.get("items", [])
        drop   = tuple(state.get("drop_off") or (state.get("drop_off_zones") or [[]])[0])

        active  = next((o for o in orders if o.get("status")=="active"  and not o.get("complete")), None)
        preview = next((o for o in orders if o.get("status")=="preview" and not o.get("complete")), None)

        useful = self._inv_useful(active, inv)
        want   = self._to_pick(active, preview, inv)
        full   = len(inv) >= 3

        def go(target_pos):
            path = bfs(pos, target_pos, blocked, self.width, self.height, reserved)
            if len(path) > 1:
                nxt = path[1]
                reserved.add(nxt)
                return {"bot": bid, "action": direction_from_move(pos, nxt)}
            reserved.add(pos)
            return {"bot": bid, "action": "wait"}

        def go_adj(target_pos):
            path = bfs_to_adjacent(pos, target_pos, blocked, self.width, self.height, reserved)
            if len(path) > 1:
                nxt = path[1]
                reserved.add(nxt)
                return {"bot": bid, "action": direction_from_move(pos, nxt)}
            reserved.add(pos)
            return {"bot": bid, "action": "wait"}

        # 1. At drop-off with useful items → deliver
        if pos == drop and useful > 0:
            reserved.add(pos)
            return {"bot": bid, "action": "drop_off"}

        # 2. Inventory full OR nothing left to pick → deliver
        if useful > 0 and (full or not want):
            if pos == drop:
                reserved.add(pos)
                return {"bot": bid, "action": "drop_off"}
            return go(drop)

        # 3. Adjacent wanted item → pick up immediately
        if len(inv) < 3 and want:
            for it in items:
                if it["id"] in assigned_ids: continue
                ip = tuple(it["position"])
                if manhattan(pos, ip) != 1: continue
                if it["type"] in want:
                    assigned_ids.add(it["id"])
                    reserved.add(pos)
                    return {"bot": bid, "action": "pick_up", "item_id": it["id"]}

        # 4. Move toward nearest wanted item
        if len(inv) < 3 and want:
            for typ in want:
                cands = [it for it in items if it["type"] == typ and it["id"] not in assigned_ids]
                if not cands:
                    cands = [it for it in items if it["type"] == typ]
                if cands:
                    cands.sort(key=lambda x: manhattan(pos, tuple(x["position"])))
                    tgt = cands[0]
                    assigned_ids.add(tgt["id"])
                    return go_adj(tuple(tgt["position"]))

        # 5. Fallback: deliver if anything useful
        if useful > 0:
            if pos == drop:
                reserved.add(pos)
                return {"bot": bid, "action": "drop_off"}
            return go(drop)

        reserved.add(pos)
        return {"bot": bid, "action": "wait"}

    def decide(self, state: dict) -> dict:
        """Main decision function — returns actions for all bots."""
        self.round_num = state.get("round", 0)

        grid = state.get("grid", {})
        if grid:
            self.update_grid(grid)

        bots  = state.get("bots", [])
        items = state.get("items", [])

        # impassable = walls + all item positions
        blocked  = self.walls | set(tuple(it["position"]) for it in items)
        reserved = set(tuple(b["position"]) for b in bots)  # pre-reserve current positions

        assigned_ids = set()
        actions = []
        for bot in sorted(bots, key=lambda b: b["id"]):
            a = self._plan_bot(bot, state, blocked, assigned_ids, reserved)
            actions.append(a)

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
