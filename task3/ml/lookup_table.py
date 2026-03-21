"""V1+ model with n_settlements_within_5 feature."""
import json, math, os
from collections import defaultdict

DATA_DIR = "/tmp/astar_data"
FLOOR = 0.01

def load_training():
    training = defaultdict(list)
    er_rates = {}
    
    for rn in range(1, 30):  # Load all available rounds
        for seed in range(5):
            path = f"{DATA_DIR}/round{rn}_gt_seed{seed}.json"
            if not os.path.exists(path): continue
            with open(path) as f:
                data = json.load(f)
            grid = data["initial_grid"]; truth = data["ground_truth"]
            H, W = len(grid), len(grid[0])
            setts = [(y,x) for y in range(H) for x in range(W) if grid[y][x] == 1]
            
            near = [(y,x) for y in range(H) for x in range(W)
                    if grid[y][x] in (4,11,0) and setts and
                    min(abs(y-sy)+abs(x-sx) for sy,sx in setts) <= 2]
            er = sum(truth[y][x][1] for y,x in near)/len(near) if near else 0.1
            er_rates[(rn,seed)] = er
            
            for y in range(H):
                for x in range(W):
                    val = grid[y][x]
                    if val in (10,5): continue
                    dists = sorted(abs(y-sy)+abs(x-sx) for sy,sx in setts) if setts else [99]
                    dist = min(dists[0], 15)
                    oa = 0
                    for dy,dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                        ny,nx = y+dy,x+dx
                        if 0<=ny<H and 0<=nx<W and grid[ny][nx]==10: oa=1; break
                    nb = min(sum(1 for sy,sx in setts if abs(y-sy)+abs(x-sx)<=3), 5)
                    n5 = min(sum(1 for d in dists if d<=5), 6)
                    training[(val,dist,oa,nb,n5)].append((er, truth[y][x]))
    
    return training, er_rates

def predict_cell(training, key, ter, bw=0.05):
    data = list(training.get(key, []))
    val, dist, oa, nb, n5 = key
    if len(data) < 5:
        for v5 in range(8): data += training.get((val,dist,oa,nb,v5), [])
    if len(data) < 5:
        for vnb in range(6):
            for v5 in range(8): data += training.get((val,dist,oa,vnb,v5), [])
    if len(data) < 5:
        for voa in [0,1]:
            for vnb in range(6):
                for v5 in range(8): data += training.get((val,dist,voa,vnb,v5), [])
    if len(data) < 5:
        for dd in [-1,1]:
            for voa in [0,1]:
                for vnb in range(6):
                    for v5 in range(8): data += training.get((val,max(0,dist+dd),voa,vnb,v5), [])
    if not data: return [1/6]*6
    pred = [0.0]*6; tw = 0
    for er, gt in data:
        w = math.exp(-((er-ter)**2)/(2*bw**2))
        for i in range(6): pred[i] += w*gt[i]
        tw += w
    return [p/tw for p in pred] if tw > 0 else [1/6]*6

def predict_full_map(training, grid, target_er):
    H, W = len(grid), len(grid[0])
    setts = [(y,x) for y in range(H) for x in range(W) if grid[y][x] == 1]
    prediction = []
    for y in range(H):
        row = []
        for x in range(W):
            val = grid[y][x]
            if val == 10: row.append([1,0,0,0,0,0]); continue
            if val == 5: row.append([0,0,0,0,0,1]); continue
            dists = sorted(abs(y-sy)+abs(x-sx) for sy,sx in setts) if setts else [99]
            dist = min(dists[0], 15)
            oa = 0
            for dy,dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                ny,nx = y+dy,x+dx
                if 0<=ny<H and 0<=nx<W and grid[ny][nx]==10: oa=1; break
            nb = min(sum(1 for sy,sx in setts if abs(y-sy)+abs(x-sx)<=3), 5)
            n5 = min(sum(1 for d in dists if d<=5), 6)
            key = (val, dist, oa, nb, n5)
            p = predict_cell(training, key, target_er)
            row.append(p)
        prediction.append(row)
    
    for y in range(H):
        for x in range(W):
            p = prediction[y][x]
            p = [max(v, FLOOR) for v in p]
            s = sum(p); prediction[y][x] = [v/s for v in p]
    return prediction

if __name__ == "__main__":
    print("Loading V1+ model...")
    training, er_rates = load_training()
    print(f"Keys: {len(training)}")
