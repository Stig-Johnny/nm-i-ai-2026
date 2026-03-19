#!/usr/bin/env python3
"""
Grocery Bot — NM i AI 2026 Warm-Up (iClaw-E merged version)
============================================================
Combines:
  - Hungarian algorithm for optimal bot→item assignment (from Codi-E's bot)
  - A* pathfinding with items-as-walls (from iClaw-E v2)
  - Strict inventory management — never over-pick (key fix vs v1)
  - Order completion priority (+5 bonus >> +1 item)
  - Preview-order pre-fetching (spare slots after active order covered)
  - Reservation table for multi-bot collision avoidance

Discovered constraints:
  - Items BLOCK movement (must include in A*/BFS blocked set)
  - pick_up requires Manhattan dist == 1 to item cell
  - drop_off only removes items matching ACTIVE order; extras stay forever
  - Shelves are INFINITE — same item_id reappears after pickup
  - Never pick more of a type than orders (active+preview) need
  - 60s cooldown between games; 40/hr; 300/day

Usage:
    python3 warmup/bot_iclawe.py --url "wss://game.ainm.no/ws?token=TOKEN"
    python3 warmup/bot_iclawe.py --auto easy 3          # needs access_token.txt
"""
import argparse
import asyncio
import heapq
import json
import sys
import urllib.request
from collections import deque

import websockets

try:
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ── Pathfinding ────────────────────────────────────────────────────────────────

def heuristic(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar(start, goal, walls_and_items, width, height, reserved=None):
    """A* toward a walkable goal. Returns first action string or None if at goal."""
    s, g = tuple(start), tuple(goal)
    if s == g: return None
    impass = set(walls_and_items)
    bl = reserved or set()
    DIRS = [("move_up",(0,-1)), ("move_down",(0,1)), ("move_left",(-1,0)), ("move_right",(1,0))]

    open_set = [(heuristic(s,g), 0, s, None)]
    visited = {}
    while open_set:
        f, gc, pos, first = heapq.heappop(open_set)
        if pos in visited: continue
        visited[pos] = True
        for act, (dx, dy) in DIRS:
            n = (pos[0]+dx, pos[1]+dy)
            if not (0 <= n[0] < width and 0 <= n[1] < height): continue
            if n in impass: continue
            if n in visited: continue
            mv = first or act
            ng = gc + 1
            if n == g: return mv
            if n not in bl:
                heapq.heappush(open_set, (ng + heuristic(n,g), ng, n, mv))
    return "wait"


def astar_adj(start, target, walls_and_items, width, height, reserved=None):
    """A* to reach a cell adjacent (Manhattan=1) to target.
    Target cell itself is excluded from blocking so BFS can approach it."""
    s, t = tuple(start), tuple(target)
    if heuristic(s, t) == 1: return None  # already adjacent
    impass = set(walls_and_items) - {t}
    bl = reserved or set()
    DIRS = [("move_up",(0,-1)), ("move_down",(0,1)), ("move_left",(-1,0)), ("move_right",(1,0))]

    def h(p): return min(heuristic(p, (t[0]+dx, t[1]+dy)) for _,(dx,dy) in DIRS)

    open_set = [(h(s), 0, s, None)]
    visited = {}
    while open_set:
        f, gc, pos, first = heapq.heappop(open_set)
        if pos in visited: continue
        visited[pos] = True
        for act, (dx, dy) in DIRS:
            n = (pos[0]+dx, pos[1]+dy)
            if not (0 <= n[0] < width and 0 <= n[1] < height): continue
            if n in impass: continue
            if n in visited: continue
            mv = first or act
            ng = gc + 1
            if heuristic(n, t) == 1: return mv
            if n not in bl:
                heapq.heappush(open_set, (ng + h(n), ng, n, mv))
    return "wait"


def apply_move(pos, move):
    if not move or not move.startswith("move_"): return tuple(pos)
    dx, dy = {"move_up":(0,-1),"move_down":(0,1),"move_left":(-1,0),"move_right":(1,0)}[move]
    return (pos[0]+dx, pos[1]+dy)


# ── Inventory & order helpers ──────────────────────────────────────────────────

def order_still_needs(order):
    """Item types the order still needs delivered (not counting inventory)."""
    needed = list(order.get("items_required", []))
    for d in order.get("items_delivered", []):
        if d in needed: needed.remove(d)
    return needed


def inv_useful_count(order, inventory):
    """How many items in inventory can be delivered to this order right now."""
    needed = order_still_needs(order)
    count = 0
    inv = list(inventory)
    for t in needed:
        if t in inv:
            count += 1
            inv.remove(t)
    return count


def to_pick(active, preview, inventory):
    """
    Types to still pick up — active first, preview fills spare slots.
    Returns list of types in priority order.
    Never picks more than the orders require.
    """
    inv = list(inventory)
    result = []

    if active:
        needed = order_still_needs(active)
        for t in needed:
            if t in inv:
                inv.remove(t)
            else:
                result.append(t)

    # Preview: only if there's room after active items
    slots_left = 3 - len(inventory) - len(result)
    if preview and slots_left > 0:
        needed = order_still_needs(preview)
        for t in needed:
            if slots_left <= 0: break
            if t in inv:
                inv.remove(t)
            else:
                result.append(t)
                slots_left -= 1

    return result


# ── Assignment ─────────────────────────────────────────────────────────────────

def assign_hungarian(bots_needing_items, targets):
    """Optimal bot→target assignment via Hungarian algorithm (or greedy fallback)."""
    if not bots_needing_items or not targets:
        return {}

    n_b, n_t = len(bots_needing_items), len(targets)

    if HAS_SCIPY:
        cost = [[heuristic(tuple(b["position"]), tuple(t["position"]))
                 for t in targets] for b in bots_needing_items]
        import numpy as np
        cost_np = np.array(cost, dtype=float)
        row_idx, col_idx = linear_sum_assignment(cost_np)
        return {bots_needing_items[r]["id"]: targets[c]
                for r, c in zip(row_idx, col_idx)}
    else:
        # Greedy closest-first
        assignments = {}
        used = set()
        for bot in bots_needing_items:
            bpos = tuple(bot["position"])
            best = min(
                ((j, t) for j, t in enumerate(targets) if j not in used),
                key=lambda jt: heuristic(bpos, tuple(jt[1]["position"])),
                default=None
            )
            if best:
                j, t = best
                assignments[bot["id"]] = t
                used.add(j)
        return assignments


# ── Per-bot decision ───────────────────────────────────────────────────────────

def plan_bot(bot, state, impass, assigned_item_ids, reserved):
    """Plan one bot's action. Returns action dict."""
    bid  = bot["id"]
    pos  = list(bot["position"])
    inv  = list(bot["inventory"])

    W    = state["grid"]["width"]
    H    = state["grid"]["height"]
    items  = state.get("items", [])
    orders = state.get("orders", [])
    drop   = list(state.get("drop_off") or (state.get("drop_off_zones") or [[]])[0])

    active  = next((o for o in orders if o.get("status")=="active"  and not o.get("complete")), None)
    preview = next((o for o in orders if o.get("status")=="preview" and not o.get("complete")), None)

    useful  = inv_useful_count(active, inv) if active else 0
    want    = to_pick(active, preview, inv)
    full    = len(inv) >= 3

    def reserve_and(action_dict):
        if action_dict["action"].startswith("move_"):
            npos = apply_move(pos, action_dict["action"])
            reserved.add(npos)
        else:
            reserved.add(tuple(pos))
        return action_dict

    # 1. At drop-off with useful items → deliver
    if pos == drop and useful > 0:
        reserved.add(tuple(pos))
        return {"bot": bid, "action": "drop_off"}

    # 2. Inventory full or nothing more to pick → go deliver
    if useful > 0 and (full or not want):
        if pos == drop:
            reserved.add(tuple(pos))
            return {"bot": bid, "action": "drop_off"}
        mv = astar(pos, drop, impass, W, H, reserved)
        return reserve_and({"bot": bid, "action": mv or "wait"})

    # 3. Adjacent wanted item → pick up immediately
    if len(inv) < 3 and want:
        for it in items:
            if it["id"] in assigned_item_ids: continue
            ip = it["position"]
            if heuristic(pos, ip) != 1: continue
            if it["type"] in want:
                assigned_item_ids.add(it["id"])
                reserved.add(tuple(pos))
                return {"bot": bid, "action": "pick_up", "item_id": it["id"]}

    # 4. Move toward nearest wanted item (from assignment or greedy)
    if len(inv) < 3 and want:
        for typ in want:
            cands = [it for it in items if it["type"] == typ and it["id"] not in assigned_item_ids]
            if not cands:
                cands = [it for it in items if it["type"] == typ]
            if cands:
                cands.sort(key=lambda x: heuristic(pos, x["position"]))
                tgt = cands[0]
                assigned_item_ids.add(tgt["id"])
                mv = astar_adj(pos, tgt["position"], impass, W, H, reserved)
                return reserve_and({"bot": bid, "action": mv or "wait"})

    # 5. Fallback: deliver if anything useful
    if useful > 0:
        if pos == drop:
            reserved.add(tuple(pos))
            return {"bot": bid, "action": "drop_off"}
        mv = astar(pos, drop, impass, W, H, reserved)
        return reserve_and({"bot": bid, "action": mv or "wait"})

    reserved.add(tuple(pos))
    return {"bot": bid, "action": "wait"}


# ── Main loop ──────────────────────────────────────────────────────────────────

async def run(url):
    print(f"Connecting to {url[:70]}...")
    async with websockets.connect(url) as ws:
        print("Connected!")
        rnd = 0
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                state = json.loads(msg)
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
                items = state.get("items", [])

                if rnd % 30 == 0:
                    invs = [b["inventory"] for b in bots]
                    print(f"Rnd {rnd:3d} | Score {score:3d} | bots={len(bots)} | inv={invs}")

                # Build impassable set: walls + all item positions
                walls   = set(map(tuple, state["grid"].get("walls", [])))
                iposset = set(map(tuple, (it["position"] for it in items)))
                impass  = walls | iposset

                assigned_ids = set()
                reserved     = set()
                # Pre-reserve current bot positions
                for b in bots:
                    reserved.add(tuple(b["position"]))

                actions = []
                for bot in sorted(bots, key=lambda b: b["id"]):
                    a = plan_bot(bot, state, impass, assigned_ids, reserved)
                    actions.append(a)

                await ws.send(json.dumps({"actions": actions, "round": rnd}))

            except asyncio.TimeoutError:
                print("Timeout"); break
            except websockets.exceptions.ConnectionClosed as e:
                print(f"Closed: {e}"); break


# ── Token helper ───────────────────────────────────────────────────────────────

MAPS = {
    "easy":      "3c7e90e6-e4bc-4095-a42b-e04eb6738809",
    "medium":    "0aba093f-a942-4a65-88ed-c60eb50b1c4a",
    "hard":      "9bb9b3de-7a56-4d5e-a4d4-637b08a526c8",
}

def get_game_url(access_token, map_name):
    mid = MAPS.get(map_name, map_name)
    h = {"Cookie": f"access_token={access_token}", "Content-Type": "application/json"}
    data = json.dumps({"map_id": mid}).encode()
    req = urllib.request.Request("https://api.ainm.no/games/request", data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        token = json.loads(r.read())["token"]
    return f"wss://game.ainm.no/ws?token={token}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="WebSocket URL with token")
    parser.add_argument("--auto", metavar="MAP", help="Map name (easy/medium/hard) — reads access_token.txt")
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()

    if args.url:
        asyncio.run(run(args.url))
    elif args.auto:
        try:
            token = open("access_token.txt").read().strip()
        except FileNotFoundError:
            print("Put your access_token JWT in access_token.txt")
            sys.exit(1)
        for i in range(args.rounds):
            print(f"\n=== Game {i+1}/{args.rounds} ===")
            url = get_game_url(token, args.auto)
            asyncio.run(run(url))
            if i < args.rounds - 1:
                print("Waiting 65s for cooldown...")
                asyncio.get_event_loop().run_until_complete(asyncio.sleep(65))
    else:
        parser.print_help()
