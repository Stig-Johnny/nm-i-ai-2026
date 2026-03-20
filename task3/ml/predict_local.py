#!/usr/bin/env python3
"""Local CNN inference for Astar Island predictions. No scipy needed."""
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import json

class ConvBlock(nn.Module):
    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.GELU(),
            nn.Conv2d(out_ch, out_ch, 3, padding=1),
            nn.BatchNorm2d(out_ch),
            nn.GELU()
        )
    def forward(self, x): return self.conv(x)

class AstarUNet(nn.Module):
    def __init__(self, in_ch=12, out_ch=6):
        super().__init__()
        self.enc1 = ConvBlock(in_ch, 64)
        self.enc2 = ConvBlock(64, 128)
        self.enc3 = ConvBlock(128, 256)
        self.bottleneck = ConvBlock(256, 512)
        self.up3 = nn.ConvTranspose2d(512, 256, 2, stride=2)
        self.dec3 = ConvBlock(512, 256)
        self.up2 = nn.ConvTranspose2d(256, 128, 2, stride=2)
        self.dec2 = ConvBlock(256, 128)
        self.up1 = nn.ConvTranspose2d(128, 64, 2, stride=2)
        self.dec1 = ConvBlock(128, 64)
        self.out_conv = nn.Conv2d(64, out_ch, 1)
        self.pool = nn.MaxPool2d(2)
    
    def forward(self, x):
        x = F.pad(x, (4,4,4,4), mode='reflect')
        e1 = self.enc1(x)
        e2 = self.enc2(self.pool(e1))
        e3 = self.enc3(self.pool(e2))
        b = self.bottleneck(self.pool(e3))
        d3 = self.dec3(torch.cat([self.up3(b), e3], 1))
        d2 = self.dec2(torch.cat([self.up2(d3), e2], 1))
        d1 = self.dec1(torch.cat([self.up1(d2), e1], 1))
        out = self.out_conv(d1)[:, :, 4:-4, 4:-4]
        out = F.softmax(out, dim=1)
        out = torch.clamp(out, min=0.01)
        return out / out.sum(dim=1, keepdim=True)

def build_features(grid):
    """Build input channels from grid. Pure numpy, no scipy."""
    grid = np.array(grid)
    H, W = grid.shape
    channels = []
    
    # Terrain one-hot
    for val in [10, 11, 1, 2, 3, 4, 5]:
        channels.append((grid == val).astype(np.float32))
    
    # Distance to settlement (Manhattan, brute force)
    setts = list(zip(*np.where((grid == 1) | (grid == 2))))
    dist = np.full((H, W), 20.0, dtype=np.float32)
    if setts:
        for y in range(H):
            for x in range(W):
                dist[y,x] = min(abs(y-sy)+abs(x-sx) for sy,sx in setts)
    channels.append(np.clip(dist / 20.0, 0, 1))
    
    # Settlement density (count in 5x5 window using convolution)
    sett_mask = ((grid == 1) | (grid == 2)).astype(np.float32)
    # Simple box filter
    density = np.zeros((H, W), dtype=np.float32)
    for y in range(H):
        for x in range(W):
            y0, y1 = max(0,y-5), min(H,y+6)
            x0, x1 = max(0,x-5), min(W,x+6)
            density[y,x] = sett_mask[y0:y1, x0:x1].sum()
    channels.append(np.clip(density / 10.0, 0, 1))
    
    # Coastal mask
    ocean = (grid == 10).astype(np.float32)
    coastal = np.zeros((H, W), dtype=np.float32)
    for y in range(H):
        for x in range(W):
            for dy, dx in [(-1,0),(1,0),(0,-1),(0,1)]:
                ny, nx = y+dy, x+dx
                if 0<=ny<H and 0<=nx<W and grid[ny,nx] == 10:
                    coastal[y,x] = 1.0; break
    channels.append(coastal)
    
    # Expansion rate placeholder (will be set externally)
    channels.append(np.full((H, W), 0.15, dtype=np.float32))
    
    # Forest density
    forest = (grid == 4).astype(np.float32)
    forest_dens = np.zeros((H, W), dtype=np.float32)
    for y in range(H):
        for x in range(W):
            y0, y1 = max(0,y-3), min(H,y+4)
            x0, x1 = max(0,x-3), min(W,x+4)
            forest_dens[y,x] = forest[y0:y1, x0:x1].sum()
    channels.append(np.clip(forest_dens / 15.0, 0, 1))
    
    return np.stack(channels, axis=0)

# Global model instance
_model = None

def load_model(model_path="/tmp/astar_ml/best_model.pt"):
    global _model
    if _model is None:
        _model = AstarUNet(in_ch=12, out_ch=6)
        _model.load_state_dict(torch.load(model_path, map_location='cpu', weights_only=True))
        _model.eval()
    return _model

def predict_cnn(grid, er=0.15):
    """Predict 40x40x6 probability tensor using CNN."""
    model = load_model()
    x = build_features(grid)
    x[10] = er  # Set expansion rate channel
    x = torch.from_numpy(x).unsqueeze(0)
    
    with torch.no_grad():
        pred = model(x)
    
    return pred[0].numpy().transpose(1, 2, 0).tolist()  # 40x40x6

if __name__ == '__main__':
    # Quick test
    import time
    grid = [[10]*40 for _ in range(40)]  # dummy
    t0 = time.time()
    load_model()
    print(f"Model loaded in {time.time()-t0:.2f}s")
    t0 = time.time()
    pred = predict_cnn(grid, 0.1)
    print(f"Prediction in {time.time()-t0:.2f}s")
    print(f"Shape: {len(pred)}x{len(pred[0])}x{len(pred[0][0])}")
