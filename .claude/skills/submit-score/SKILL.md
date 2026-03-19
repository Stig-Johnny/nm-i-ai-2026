# /submit-score

Record a new score and update docs.

## Usage
```
/submit-score task1 easy 126
/submit-score task2 medium 85
```

## Steps
1. Update `docs/tasks/taskN.md` with new score
2. Update `docs/warmup/scores.md` if warm-up task
3. Commit with message: `taskN: score <score> on <difficulty>`
4. Push to main
5. Post score to Discord #iclaw-e
