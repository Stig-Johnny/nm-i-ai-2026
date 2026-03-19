# Strategy Overview

## Scoring

Each task normalized 0-100, averaged equally. Skipping a task = 0 for that task.

**Priority:** Get ANY score on all 3 tasks first, then optimize.

## Team Split

| Agent | Role |
|-------|------|
| Claude-5 | Primary coder, hardest task |
| iClaw-E | LLM task + ML task first pass |
| Stig | Account, submissions, platform access |

## Expected Task Types

Based on pre-competition intel and typical AI competition patterns:

| Task | Likely Type | CPU Approach |
|------|-------------|-------------|
| Task 1 | Computer Vision | CLIP/EfficientNet-B0 ONNX (~30ms/img) |
| Task 2 | Language Model | Claude Haiku API |
| Task 3 | Machine Learning | XGBoost + Optuna |

## Constraints

- **No GPU** — all inference CPU or API-based
- **Rate limits** — unknown for main tasks
- **69 hours** — must prioritize breadth over depth
