#!/usr/bin/env python3
"""Fast training - precomputes features with numpy."""
import torch
import torch.nn as nn
import torch.nn.functional as F
import json
import numpy as np
from torch.utils.data import Dataset, DataLoader
import time
from scipy.ndimage import distance_transform_cdt

class AstarDataset(Dataset):
    def __init__(self, data_path, augment=True):
        with open(data_path) as f:
            raw = json.load(f)
        
        print(f"Building features for {len(raw)} maps...")
        t0 = time.time()
        self.samples = []
        
        for idx, item in enumerate(raw):
            grid = np.array(item['grid'])
            truth = np.array(item['truth'], dtype=np.float32)
            
            x = self._build_features(grid)
            y = truth.transpose(2, 0, 1)  # (6, H, W)
            
            self.samples.append((x, y))
            
            if augment:
                for k in range(1, 4):
                    self.samples.append((np.rot90(x, k, axes=(1,2)).copy(), np.rot90(y, k, axes=(1,2)).copy()))
                self.samples.append((x[:,::-1,:].copy(), y[:,::-1,:].copy()))
                self.samples.append((x[:,:,::-1].copy(), y[:,:,::-1].copy()))
                self.samples.append((x[:,::-1,::-1].copy(), y[:,::-1,::-1].copy()))
            
            if (idx+1) % 10 == 0:
                print(f"  {idx+1}/{len(raw)} maps processed...")
        
        print(f"Dataset: {len(self.samples)} samples in {time.time()-t0:.1f}s")
    
    def _build_features(self, grid):
        H, W = grid.shape
        channels = []
        
        # Terrain one-hot
        for val in [10, 11, 1, 2, 3, 4, 5]:
            channels.append((grid == val).astype(np.float32))
        
        # Distance to settlement (fast with scipy)
        sett_mask = (grid == 1) | (grid == 2)
        if sett_mask.any():
            dist = distance_transform_cdt(~sett_mask).astype(np.float32)
        else:
            dist = np.full((H, W), 20.0, dtype=np.float32)
        channels.append(np.clip(dist / 20.0, 0, 1))
        
        # Settlement density (convolution-based)
        sett_float = sett_mask.astype(np.float32)
        from scipy.ndimage import uniform_filter
        density = uniform_filter(sett_float, size=11, mode='constant') * 121
        channels.append(np.clip(density / 10.0, 0, 1))
        
        # Coastal mask
        ocean = (grid == 10).astype(np.float32)
        from scipy.ndimage import maximum_filter
        ocean_adj = maximum_filter(ocean, size=3) - ocean
        coastal = (ocean_adj > 0).astype(np.float32)
        channels.append(coastal)
        
        # Expansion rate (from near-settlement transitions)
        setts = list(zip(*np.where(grid == 1)))
        if setts and len(setts) > 0:
            # Estimate from training data relationship
            n_setts = len(setts)
            er = min(n_setts / 100.0, 0.5)  # rough proxy
        else:
            er = 0.15
        channels.append(np.full((H, W), er, dtype=np.float32))
        
        # Forest density
        forest = (grid == 4).astype(np.float32)
        forest_dens = uniform_filter(forest, size=7, mode='constant') * 49
        channels.append(np.clip(forest_dens / 15.0, 0, 1))
        
        return np.stack(channels, axis=0).astype(np.float32)  # (C, H, W)
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        x, y = self.samples[idx]
        return torch.from_numpy(x), torch.from_numpy(y)

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

def train():
    device = torch.device('cuda')
    print(f"Device: {device}")
    
    dataset = AstarDataset('training_data.json', augment=True)
    loader = DataLoader(dataset, batch_size=16, shuffle=True, num_workers=0, pin_memory=True)
    
    model = AstarUNet(in_ch=12, out_ch=6).to(device)
    print(f"Model params: {sum(p.numel() for p in model.parameters()):,}")
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=300)
    
    best_score = 0
    import math
    
    for epoch in range(300):
        model.train()
        total_loss = 0; n = 0
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            pred = model(x)
            # Entropy-weighted KL loss
            eps = 1e-8
            entropy = -(y * torch.log(y + eps)).sum(1)
            kl = (y * torch.log((y + eps) / (pred + eps))).sum(1)
            loss = (entropy * kl).sum() / (entropy.sum() + eps)
            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            total_loss += loss.item(); n += 1
        scheduler.step()
        
        if (epoch+1) % 20 == 0:
            model.eval()
            scores = []
            with torch.no_grad():
                for x, y in loader:
                    x, y = x.to(device), y.to(device)
                    pred = model(x)
                    for i in range(x.size(0)):
                        p = pred[i].cpu().numpy().transpose(1,2,0)
                        t = y[i].cpu().numpy().transpose(1,2,0)
                        tkl = tent = 0
                        for cy in range(40):
                            for cx in range(40):
                                e = -sum(v*math.log(v) for v in t[cy,cx] if v>0)
                                if e > 0.01:
                                    k = sum(t[cy,cx,j]*math.log(t[cy,cx,j]/(p[cy,cx,j]+1e-8)) for j in range(6) if t[cy,cx,j]>0)
                                    tkl += e*k; tent += e
                        scores.append(100*math.exp(-3*tkl/tent) if tent>0 else 0)
            avg = sum(scores)/len(scores)
            print(f"Epoch {epoch+1:3d}: loss={total_loss/n:.6f}, score={avg:.1f}", flush=True)
            if avg > best_score:
                best_score = avg
                torch.save(model.state_dict(), 'best_model.pt')
                print(f"  NEW BEST: {best_score:.1f}", flush=True)
    
    print(f"\nDone. Best score: {best_score:.1f}")

if __name__ == '__main__':
    train()
