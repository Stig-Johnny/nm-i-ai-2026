# /astar-round

Handle an Astar Island round — check status, submit predictions, monitor scores.

## Steps

1. Check round status: `python task3/solution.py --poll` (background) or manual check
2. If active round with queries available: `python task3/solution.py --explore`
3. If active round with 0 queries: `python task3/solution.py --priors` (resubmit improved priors)
4. If round completed: check scores at `GET /astar-island/my-rounds`
5. If round scored: get analysis at `GET /astar-island/analysis/{round_id}/{seed_index}`

## Key Commands

```bash
# Poll for new rounds (background)
source .venv/bin/activate && python task3/solution.py --poll

# Quick status check
python -c "
from shared.token import get_access_token
import requests
s = requests.Session()
s.headers['Authorization'] = f'Bearer {get_access_token()}'
rounds = s.get('https://api.ainm.no/astar-island/rounds').json()
for r in rounds: print(f'Round {r[\"round_number\"]}: {r[\"status\"]}')
my = s.get('https://api.ainm.no/astar-island/my-rounds').json()
for r in my: print(f'  Score: {r.get(\"round_score\")} Rank: {r.get(\"rank\")}')
"
```

## After Round Completes

Use the analysis endpoint to learn from mistakes:
- Compare predictions vs ground truth
- Identify which cell types we got wrong
- Update priors in `initial_grid_to_priors()` for next round

## Mechanics Quick Reference

- Ocean/Mountain: static (98% confidence)
- Settlements near coast: can become ports
- Settlements die → ruins (starvation, raids, winter)
- Ruins near settlements: reclaimed. Isolated ruins: become forest/plains
- Forest near settlements: can be cleared for expansion
- See docs/strategy/astar-island-mechanics.md for full details
