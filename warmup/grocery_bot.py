"""
Grocery Bot — NM i AI 2026 Warm-up Challenge
=============================================
Optimized multi-bot grocery store agent.

Strategy:
  - Per-bot greedy planner with active-only inventory (no preview pre-fetch)
  - A* pathfinding — treats walls AND item cells as impassable
  - Smarter approach-cell selection: BFS to nearest walkable adjacent cell
  - Hungarian algorithm for multi-bot item assignment
  - Reservation table for cooperative collision avoidance
  - Order completion focus: +5 bonus per completed order

Key constraints discovered:
  - Items BLOCK movement — path through item cells is rejected by server
  - pick_up requires Manhattan distance == 1 to item cell
  - drop_off removes ONLY items matching active order; extras stay forever
  - Shelves are infinite — same item_id reappears after pickup
  - 60s cooldown between games; 40/hr; 300/day

Run:
    python warmup/grocery_bot.py --url "wss://game.ainm.no/ws?token=TOKEN"
"""

import asyncio
import heapq
import json
import sys
from collections import deque

import websockets

try:
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ============================================================
# Pathfinding
# ============================================================

DIRS = [("move_up",(0,-1)), ("move_down",(0,1)), ("move_left",(-1,0)), ("move_right",(1,0))]


def heuristic(a, b):
    return abs(a[0]-b[0]) + abs(a[1]-b[1])


def astar(start, goal, impass, width, height, reserved=None):
    """A* from start to goal. Returns first action, or None if already there.
    If path is fully blocked by reservations, retries without reservation constraint
    (temporary deadlock resolution — bot takes any available step toward goal).
    """
    s, g = tuple(start), tuple(goal)
    if s == g: return None

    def _search(bl):
        open_set = [(heuristic(s,g), 0, s, None)]
        visited = {}
        while open_set:
            f, gc, pos, first = heapq.heappop(open_set)
            if pos in visited: continue
            visited[pos] = True
            for act,(dx,dy) in DIRS:
                n = (pos[0]+dx, pos[1]+dy)
                if not (0 <= n[0] < width and 0 <= n[1] < height): continue
                if n in impass: continue
                if n in visited: continue
                mv = first or act
                ng = gc + 1
                if n == g: return mv
                if n not in bl:
                    heapq.heappush(open_set, (ng + heuristic(n,g), ng, n, mv))
        return None

    result = _search(reserved or set())
    if result is not None: return result
    # Deadlock: retry without reservations (yield to blockers next round)
    return _search(set()) or "wait"


def best_approach_cell(bot_pos, item_pos, walls, item_set, width, height):
    """
    Find the nearest walkable cell adjacent to item_pos.
    Excludes walls and other item cells (both block movement).
    Returns the approach cell, or None if no walkable adjacent cell exists.
    """
    candidates = []
    for _, (dx,dy) in DIRS:
        n = (item_pos[0]+dx, item_pos[1]+dy)
        if not (0 <= n[0] < width and 0 <= n[1] < height): continue
        if n in walls: continue
        if n in item_set and n != tuple(bot_pos): continue  # other items block
        candidates.append((heuristic(bot_pos, n), n))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def direction_from_move(current, next_pos):
    dx = next_pos[0] - current[0]
    dy = next_pos[1] - current[1]
    if dx == 1: return "move_right"
    if dx == -1: return "move_left"
    if dy == 1: return "move_down"
    if dy == -1: return "move_up"
    return "wait"


def manhattan(a, b):
    return abs(a[0]-b[0]) + abs(a[1]-b[1])


# ============================================================
# Order helpers
# ============================================================

def order_remaining_types(order):
    """Item types the order still needs (required - delivered), as a list."""
    needed = list(order.get("items_required", []))
    for d in order.get("items_delivered", []):
        if d in needed: needed.remove(d)
    return needed


def inv_useful_count(order, inventory):
    """How many inventory items match what the active order still needs."""
    if not order: return 0
    needed = order_remaining_types(order)
    count = 0
    inv = list(inventory)
    for t in needed:
        if t in inv:
            count += 1; inv.remove(t)
    return count


def types_to_pick(active, preview, inventory, global_carried=None):
    """
    Types still needed — active first, preview fills last slot.
    `global_carried`: Counter of types already carried by ALL bots (including this one).
    Prevents over-picking: if enough of a type is already being carried fleet-wide, skip it.
    """
    from collections import Counter
    carried = Counter(global_carried or {})
    inv = list(inventory)
    result = []

    if active:
        needed = order_remaining_types(active)
        needed_ctr = Counter(needed)
        for t in needed:
            # Skip if enough already carried fleet-wide (avoid duplicate pickup)
            if carried[t] >= needed_ctr[t]:
                continue
            if t in inv:
                inv.remove(t)
                # This bot already has it — don't reduce demand for other bots
            else:
                result.append(t)
                carried[t] += 1  # claim this slot fleet-wide

    # Preview: only fill last slot if there's room after active items
    slots_left = 3 - len(inventory) - len(result)
    if preview and slots_left > 0:
        for t in order_remaining_types(preview):
            if slots_left <= 0: break
            if t in inv:
                inv.remove(t)
            else:
                result.append(t)
                slots_left -= 1

    return result


# ============================================================
# Assignment (Hungarian or greedy)
# ============================================================

def assign_bots_to_items(bots_needing_items, items):
    """Assign bots to target items. Returns {bot_id: item_dict}."""
    if not bots_needing_items or not items:
        return {}
    if HAS_SCIPY:
        cost = np.array([[manhattan(tuple(b["position"]), tuple(it["position"]))
                          for it in items]
                         for b in bots_needing_items], dtype=float)
        row_idx, col_idx = linear_sum_assignment(cost)
        return {bots_needing_items[r]["id"]: items[c]
                for r, c in zip(row_idx, col_idx)}
    else:
        # Greedy
        assignments, used = {}, set()
        for bot in bots_needing_items:
            bpos = tuple(bot["position"])
            best_j, best_d = None, 9999
            for j, it in enumerate(items):
                if j in used: continue
                d = manhattan(bpos, tuple(it["position"]))
                if d < best_d:
                    best_d = d; best_j = j
            if best_j is not None:
                assignments[bot["id"]] = items[best_j]
                used.add(best_j)
        return assignments


# ============================================================
# Per-bot planner
# ============================================================

def plan_bot(bot, state, walls, item_set, impass, assigned_ids, reserved):
    """Return one action dict for this bot."""
    bid   = bot["id"]
    pos   = tuple(bot["position"])
    inv   = list(bot["inventory"])

    W     = state["grid"]["width"]
    H     = state["grid"]["height"]
    items = state.get("items", [])
    orders = state.get("orders", [])
    drop  = tuple(state.get("drop_off") or (state.get("drop_off_zones") or [[]])[0])

    active  = next((o for o in orders if o.get("status")=="active"  and not o.get("complete")), None)
    preview = next((o for o in orders if o.get("status")=="preview" and not o.get("complete")), None)

    useful = inv_useful_count(active, inv)
    want   = types_to_pick(active, preview, inv, state.get("_global_carried"))
    full   = len(inv) >= 3

    def go(target):
        mv = astar(pos, target, impass, W, H, reserved)
        npos = _apply(pos, mv) if mv and mv != "wait" else pos
        reserved.add(npos)
        return {"bot": bid, "action": mv or "wait"}

    def go_approach(item_pos):
        app = best_approach_cell(pos, item_pos, walls, item_set, W, H)
        if app is None:
            reserved.add(pos); return {"bot": bid, "action": "wait"}
        if pos == app:
            reserved.add(pos); return None  # already there, caller handles pickup
        mv = astar(pos, app, impass, W, H, reserved)
        npos = _apply(pos, mv) if mv and mv != "wait" else pos
        reserved.add(npos)
        return {"bot": bid, "action": mv or "wait"}

    # 1. At drop-off with useful items → deliver
    if pos == drop and useful > 0:
        reserved.add(pos)
        return {"bot": bid, "action": "drop_off"}

    # 2. Inventory full OR nothing left to pick OR drop is closer than nearest item → deliver
    def nearest_item_dist():
        if not want: return 9999
        best = 9999
        want_set = set(want)
        for it in items:
            if it["type"] not in want_set: continue
            app = best_approach_cell(pos, tuple(it["position"]), walls, item_set, W, H)
            if app: best = min(best, manhattan(pos, app))
        return best

    drop_dist = manhattan(pos, drop)
    num_bots = len(state.get("bots", []))
    # Early delivery only for multi-bot maps — single bot should fill inventory first
    early_deliver = drop_dist <= nearest_item_dist() if num_bots >= 3 else False
    should_deliver = useful > 0 and (full or not want or early_deliver)
    if should_deliver:
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

    # 4. Move toward nearest wanted item of ANY needed type (best approach cell)
    if len(inv) < 3 and want:
        want_set = set(want)
        # Gather all candidate items for any wanted type
        all_cands = []
        for it in items:
            if it["type"] not in want_set: continue
            if it["id"] in assigned_ids: continue
            ip = tuple(it["position"])
            app = best_approach_cell(pos, ip, walls, item_set, W, H)
            if app is None: continue
            all_cands.append((manhattan(pos, app), it, app))
        if not all_cands:
            # Shelves refill — retry without assigned filter
            for it in items:
                if it["type"] not in want_set: continue
                ip = tuple(it["position"])
                app = best_approach_cell(pos, ip, walls, item_set, W, H)
                if app is None: continue
                all_cands.append((manhattan(pos, app), it, app))
        if all_cands:
            all_cands.sort(key=lambda x: x[0])
            _, tgt, app = all_cands[0]
            assigned_ids.add(tgt["id"])
            tpos = tuple(tgt["position"])
            # Already adjacent?
            if manhattan(pos, tpos) == 1:
                reserved.add(pos)
                return {"bot": bid, "action": "pick_up", "item_id": tgt["id"]}
            # BFS to the pre-computed approach cell
            mv = astar(pos, app, impass, W, H, reserved)
            npos = _apply(pos, mv) if mv and mv != "wait" else pos
            reserved.add(npos)
            return {"bot": bid, "action": mv or "wait"}

    # 5. Fallback: deliver if anything useful
    if useful > 0:
        if pos == drop:
            reserved.add(pos)
            return {"bot": bid, "action": "drop_off"}
        return go(drop)

    reserved.add(pos)
    return {"bot": bid, "action": "wait"}


def _apply(pos, move):
    if not move or not move.startswith("move_"): return pos
    dx,dy = {"move_up":(0,-1),"move_down":(0,1),"move_left":(-1,0),"move_right":(1,0)}[move]
    return (pos[0]+dx, pos[1]+dy)


# ============================================================
# GroceryAgent
# ============================================================

class GroceryAgent:
    def __init__(self):
        self.width = self.height = 0
        self.walls = set()

    def decide(self, state):
        grid = state.get("grid", {})
        if grid:
            self.width  = grid.get("width", self.width)
            self.height = grid.get("height", self.height)
            self.walls  = set(map(tuple, grid.get("walls", [])))

        bots  = state.get("bots", [])
        items = state.get("items", [])

        item_set = set(map(tuple, (it["position"] for it in items)))
        impass   = self.walls | item_set
        reserved = set(map(tuple, (b["position"] for b in bots)))

        # Build global_carried: count of each type currently in ALL bot inventories
        # that matches what the active order still needs. Used to avoid bots picking
        # more of a type than required fleet-wide.
        from collections import Counter
        active_order = next((o for o in state.get("orders",[])
                             if o.get("status")=="active" and not o.get("complete")), None)
        needed_types = set(order_remaining_types(active_order)) if active_order else set()
        global_carried = Counter()
        for b in bots:
            for t in b.get("inventory", []):
                if t in needed_types:
                    global_carried[t] += 1
        state["_global_carried"] = global_carried

        assigned_ids = set()
        actions = []
        for bot in sorted(bots, key=lambda b: b["id"]):
            a = plan_bot(bot, state, self.walls, item_set, impass, assigned_ids, reserved)
            actions.append(a)

        state.pop("_global_carried", None)
        return {"actions": actions}


# ============================================================
# WebSocket client
# ============================================================

agent = GroceryAgent()


async def run(url):
    print(f"Connecting to {url[:70]}...")
    async with websockets.connect(url) as ws:
        print("Connected!")
        rnd = 0
        async for message in ws:
            state = json.loads(message)
            t = state.get("type")
            if t == "game_over":
                print(f"\nGame over! Score: {state.get('score',0)}"
                      f" | Items: {state.get('items_delivered',0)}"
                      f" | Orders: {state.get('orders_completed',0)}"
                      f" | Rounds: {state.get('rounds_used',0)}")
                break
            if t != "game_state": continue
            rnd   = state.get("round", rnd)
            score = state.get("score", 0)
            bots  = state.get("bots", [])
            if rnd % 50 == 0:
                invs = [b["inventory"] for b in bots]
                print(f"Rnd {rnd:3d} | Score {score:3d} | inv={invs}")
            action = agent.decide(state)
            await ws.send(json.dumps(action))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.url))
