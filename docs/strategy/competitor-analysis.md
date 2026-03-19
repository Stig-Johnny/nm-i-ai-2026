# Competitor Analysis — March 19 Evening

## NorgesGruppen Detection

**Top teams use:**
- YOLOv8m at imgsz=640
- `conf=0.001` (very low — let mAP evaluation handle filtering)
- `iou=0.50`, `max_det=500`
- **torch.load monkey-patch** for torch 2.6 compatibility in sandbox

**Our mistake:** `conf=0.5` filtered out most detections. mAP evaluation does its own threshold sweep — low conf lets it find optimal threshold.

**Best public mAP50:** 0.565 → scoring 95-100 normalized

## Astar Island

**Empirical terrain transition probabilities (from competitor analysis):**
- Settlement: 41% stays, 37% → Empty, 18% → Forest, 3% → Ruin
- Port: 32% stays, 36% → Empty, 12% → Settlement, 18% → Forest
- Forest: 75% stays, 16% → Settlement, 7% → Empty
- Plains/Empty: 78% stays, 16% → Settlement, 3% → Forest

**Spatial features:**
- Coastal cells: 16.2% chance of becoming Port (vs 0% inland)
- Near settlement (≤3 cells): Plains → Settlement 22% (vs 11% far)
- Forest reclamation: Settlements → Empty/Forest 55% more than → Ruins

**Key strategies:**
- Multi-round memory: reuse ground truth from completed rounds as priors
- 0.01 probability floor is CRITICAL
- Top team (larsendbaas): learned transition model with context features
- Spread queries for coverage, don't cluster for Monte Carlo

## Tripletex

**Two approaches observed:**
1. JSON plan generation (buggy — template variable substitution breaks multi-step workflows)
2. OpenAI function calling with iterative refinement (better — handles errors naturally)

**Common bugs in JSON plan approach:**
- `{{variable}}` templates never resolved
- Query params on PUT dropped
- Multi-step workflows fail at step 2+
