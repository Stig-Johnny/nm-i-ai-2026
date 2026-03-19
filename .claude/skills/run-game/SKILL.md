# /run-game

Run a game against the competition platform.

## Usage
```
/run-game easy
/run-game medium
/run-game hard
/run-game expert
/run-game nightmare
```

## Steps
1. Extract access token from Chrome via CDP (port 9222)
2. Request game token from `POST https://api.ainm.no/games/request`
3. Connect to WebSocket and run the bot
4. Report score

## Requirements
- Chrome running with `--remote-debugging-port=9222`
- Logged in to app.ainm.no
- `.venv` activated with deps installed

## Command
```bash
source .venv/bin/activate && python warmup/run_game.py <difficulty>
```
