#!/bin/bash
# Quick runner for all tasks
# Usage: ./run.sh task1 wss://game.ainm.no/ws?token=TOKEN
#        ./run.sh task2 wss://...
#        ./run.sh task3 wss://...

set -e
TASK=$1
URL=$2

if [ -z "$TASK" ] || [ -z "$URL" ]; then
  echo "Usage: $0 <task1|task2|task3> <wss-url>"
  exit 1
fi

source .venv/bin/activate 2>/dev/null || true

if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo "Running $TASK..."
python $TASK/solution.py --url "$URL"
