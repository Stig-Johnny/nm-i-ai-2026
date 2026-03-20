#!/usr/bin/env python3
"""
Simplified Norse World Simulator for Astar Island.
Approximates the competition simulator to generate Monte Carlo predictions.
Calibrate hidden params from observations, run 200+ times, average outcomes.
"""
import numpy as np
from collections import defaultdict

# Terrain codes
OCEAN = 10
PLAINS = 11
EMPTY = 0
SETTLEMENT = 1
PORT = 2
RUIN = 3
FOREST = 4
MOUNTAIN = 5

class Settlement:
    def __init__(self, y, x, has_port=False, owner_id=0):
        self.y = y
        self.x = x
        self.population = 1.0 + np.random.random() * 0.5
        self.food = 1.0
        self.wealth = 0.5
        self.defense = 0.5
        self.has_port = has_port
        self.alive = True
        self.owner_id = owner_id
        self.has_longship = False

class NorseSimulator:
    def __init__(self, grid, settlements_data, params=None):
        """
        grid: 40x40 array of terrain codes
        settlements_data: list of {x, y, has_port, alive} dicts
        params: dict of hidden parameters
        """
        self.H, self.W = len(grid), len(grid[0])
        self.initial_grid = np.array(grid)
        self.params = params or {}
        self.initial_settlements = settlements_data
        
    def run(self, n_years=50):
        """Run one simulation, return final grid."""
        grid = self.initial_grid.copy()
        
        # Initialize settlements
        settlements = {}
        for i, s in enumerate(self.initial_settlements):
            y, x = s['y'], s['x']
            sett = Settlement(y, x, s.get('has_port', False), owner_id=i)
            settlements[(y, x)] = sett
        
        # Hidden params with defaults
        expansion_rate = self.params.get('expansion_rate', 0.15)
        winter_severity = self.params.get('winter_severity', 0.3)
        food_per_forest = self.params.get('food_per_forest', 0.3)
        conflict_rate = self.params.get('conflict_rate', 0.1)
        ruin_reclaim_rate = self.params.get('ruin_reclaim_rate', 0.05)
        forest_regrow_rate = self.params.get('forest_regrow_rate', 0.03)
        
        for year in range(n_years):
            # === PHASE 1: GROWTH ===
            for (y, x), sett in list(settlements.items()):
                if not sett.alive: continue
                
                # Food from adjacent forest
                adj_forest = 0
                for dy, dx in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                    ny, nx = y+dy, x+dx
                    if 0<=ny<self.H and 0<=nx<self.W and grid[ny][nx] == FOREST:
                        adj_forest += 1
                
                sett.food += adj_forest * food_per_forest
                sett.population += 0.05 * sett.food if sett.food > 0.5 else -0.1
                sett.population = max(0.1, min(sett.population, 5.0))
                
                # Expansion: prosperous settlements found new settlements
                if sett.food > 1.0 and sett.population > 1.5 and np.random.random() < expansion_rate:
                    # Find adjacent buildable cell
                    candidates = []
                    for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                        ny, nx = y+dy, x+dx
                        if 0<=ny<self.H and 0<=nx<self.W and grid[ny][nx] in (PLAINS, FOREST, EMPTY) and (ny,nx) not in settlements:
                            candidates.append((ny, nx))
                    
                    if candidates:
                        ny, nx = candidates[np.random.randint(len(candidates))]
                        # Check if coastal → port
                        coastal = any(0<=ny+ddy<self.H and 0<=nx+ddx<self.W and grid[ny+ddy][nx+ddx] == OCEAN
                                     for ddy, ddx in [(-1,0),(1,0),(0,-1),(0,1)])
                        
                        new_sett = Settlement(ny, nx, has_port=coastal, owner_id=sett.owner_id)
                        new_sett.population = sett.population * 0.3
                        sett.population *= 0.7
                        settlements[(ny, nx)] = new_sett
                        grid[ny][nx] = PORT if coastal else SETTLEMENT
                
                # Port development for coastal settlements
                if not sett.has_port:
                    coastal = any(0<=y+dy<self.H and 0<=x+dx<self.W and grid[y+dy][x+dx] == OCEAN
                                 for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)])
                    if coastal and sett.wealth > 1.0 and np.random.random() < 0.1:
                        sett.has_port = True
                        grid[y][x] = PORT
                        sett.has_longship = True
            
            # === PHASE 2: CONFLICT ===
            alive_setts = [(k, v) for k, v in settlements.items() if v.alive]
            for (y, x), sett in alive_setts:
                if not sett.alive: continue
                
                # Desperate settlements raid more
                raid_prob = conflict_rate * (1.5 if sett.food < 0.3 else 0.5)
                if np.random.random() > raid_prob: continue
                
                # Find target (different owner, within range)
                raid_range = 5 if sett.has_longship else 3
                targets = [(k, v) for k, v in settlements.items() 
                          if v.alive and v.owner_id != sett.owner_id 
                          and abs(k[0]-y)+abs(k[1]-x) <= raid_range]
                
                if not targets: continue
                ty, tx = targets[np.random.randint(len(targets))][0]
                target = settlements[(ty, tx)]
                
                # Raid outcome
                attack = sett.population * (1 + sett.defense * 0.5)
                defend = target.population * (1 + target.defense)
                
                if attack > defend * (0.8 + np.random.random() * 0.4):
                    # Successful raid
                    loot = min(target.food * 0.3, 0.5)
                    sett.food += loot
                    target.food -= loot
                    target.defense -= 0.2
                    
                    # Sometimes conquer
                    if np.random.random() < 0.15:
                        target.owner_id = sett.owner_id
            
            # === PHASE 3: TRADE ===
            ports = [(k, v) for k, v in settlements.items() if v.alive and v.has_port]
            for i, ((y1, x1), p1) in enumerate(ports):
                for (y2, x2), p2 in ports[i+1:]:
                    if p1.owner_id == p2.owner_id or abs(y1-y2)+abs(x1-x2) > 15:
                        continue
                    # At war? (different owner = potential war)
                    if np.random.random() < 0.5: continue  # 50% chance of trade
                    trade_value = 0.1
                    p1.food += trade_value
                    p2.food += trade_value
                    p1.wealth += trade_value * 0.5
                    p2.wealth += trade_value * 0.5
            
            # === PHASE 4: WINTER ===
            severity = winter_severity * (0.5 + np.random.random())  # Variable each year
            for (y, x), sett in list(settlements.items()):
                if not sett.alive: continue
                
                sett.food -= severity
                
                # Collapse check
                if sett.food < -0.5 or (sett.population < 0.3 and np.random.random() < 0.3):
                    sett.alive = False
                    grid[y][x] = RUIN
                    
                    # Disperse population to nearby friendly settlements
                    nearby = [(k, v) for k, v in settlements.items() 
                             if v.alive and v.owner_id == sett.owner_id 
                             and abs(k[0]-y)+abs(k[1]-x) <= 5]
                    if nearby:
                        for _, ns in nearby:
                            ns.population += sett.population / len(nearby) * 0.5
            
            # === PHASE 5: ENVIRONMENT ===
            for y in range(self.H):
                for x in range(self.W):
                    if grid[y][x] != RUIN: continue
                    
                    # Nearby thriving settlement reclaims?
                    nearby_alive = [(k, v) for k, v in settlements.items()
                                   if v.alive and abs(k[0]-y)+abs(k[1]-x) <= 3 
                                   and v.population > 1.0]
                    
                    if nearby_alive and np.random.random() < ruin_reclaim_rate:
                        patron = nearby_alive[np.random.randint(len(nearby_alive))]
                        coastal = any(0<=y+dy<self.H and 0<=x+dx<self.W and grid[y+dy][x+dx] == OCEAN
                                     for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)])
                        new_sett = Settlement(y, x, has_port=coastal, owner_id=patron[1].owner_id)
                        new_sett.population = 0.3
                        settlements[(y, x)] = new_sett
                        grid[y][x] = PORT if coastal else SETTLEMENT
                    elif np.random.random() < forest_regrow_rate:
                        grid[y][x] = FOREST
                    elif np.random.random() < 0.02:
                        grid[y][x] = PLAINS
        
        # Convert grid to class indices for output
        class_map = {OCEAN: 0, PLAINS: 0, EMPTY: 0, SETTLEMENT: 1, PORT: 2, 
                     RUIN: 3, FOREST: 4, MOUNTAIN: 5}
        result = np.zeros((self.H, self.W), dtype=int)
        for y in range(self.H):
            for x in range(self.W):
                result[y][x] = class_map.get(grid[y][x], 0)
        
        return result
    
    def monte_carlo(self, n_runs=200):
        """Run n_runs simulations and compute probability distributions."""
        counts = np.zeros((self.H, self.W, 6), dtype=np.float32)
        
        for i in range(n_runs):
            result = self.run()
            for y in range(self.H):
                for x in range(self.W):
                    counts[y][x][result[y][x]] += 1
        
        # Normalize to probabilities
        probs = counts / n_runs
        
        # Apply floor
        probs = np.maximum(probs, 0.01)
        probs = probs / probs.sum(axis=-1, keepdims=True)
        
        return probs


def calibrate_params(grid, settlements_data, observed_er, observed_food=None):
    """Estimate hidden params from observations."""
    params = {
        'expansion_rate': observed_er * 2.5,  # Scale factor: ER obs → sim param
        'winter_severity': 0.3 if observed_er > 0.1 else 0.5,  # High ER = mild winters
        'food_per_forest': 0.3,
        'conflict_rate': 0.1 + observed_er * 0.2,  # More expansion = more conflict
        'ruin_reclaim_rate': 0.05,
        'forest_regrow_rate': 0.03,
    }
    
    if observed_food is not None:
        # High avg food → high food_per_forest, mild winters
        params['food_per_forest'] = max(0.1, observed_food * 0.5)
        params['winter_severity'] = max(0.1, 0.5 - observed_food * 0.3)
    
    return params


if __name__ == '__main__':
    import json, time
    
    # Test on R8 data
    with open('/tmp/astar_data/round8_gt_seed0.json') as f:
        d = json.load(f)
    
    grid = d['initial_grid']
    # Build settlements list
    setts = []
    for y in range(40):
        for x in range(40):
            if grid[y][x] == 1:
                setts.append({'y': y, 'x': x, 'has_port': False, 'alive': True})
            elif grid[y][x] == 2:
                setts.append({'y': y, 'x': x, 'has_port': True, 'alive': True})
    
    params = calibrate_params(grid, setts, observed_er=0.024)
    print(f"Params: {params}")
    
    sim = NorseSimulator(grid, setts, params)
    
    # Run Monte Carlo
    t0 = time.time()
    probs = sim.monte_carlo(n_runs=50)
    dt = time.time() - t0
    print(f"50 runs in {dt:.1f}s ({dt/50*1000:.0f}ms per run)")
    
    # Score against GT
    truth = np.array(d['ground_truth'])
    import math
    total_kl = total_ent = 0
    for y in range(40):
        for x in range(40):
            gt = truth[y][x]
            p = probs[y][x]
            ent = -sum(v*math.log(v) for v in gt if v > 0)
            if ent > 0.01:
                kl = sum(gt[i]*math.log(gt[i]/p[i]) for i in range(6) if gt[i] > 0)
                total_kl += ent*kl; total_ent += ent
    
    wkl = total_kl/total_ent
    score = 100*math.exp(-3*wkl)
    print(f"Simulator score on R8s0: {score:.1f} (CNN: ~81)")
