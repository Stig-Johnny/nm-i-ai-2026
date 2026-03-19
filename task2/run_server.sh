#!/bin/bash
# Starts the Tripletex agent server + cloudflared tunnel
# Restarts both if they die. Logs tunnel URL to task2/tunnel_url.txt

set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
source .venv/bin/activate

PORT=9001
LOG="$REPO/task2/server.log"
URL_FILE="$REPO/task2/tunnel_url.txt"

echo "Starting Tripletex agent on port $PORT..."

# Kill existing
pkill -f "uvicorn task2" 2>/dev/null || true
pkill cloudflared 2>/dev/null || true
sleep 2

# Start uvicorn
uvicorn task2.solution:app --host 127.0.0.1 --port $PORT >> "$LOG" 2>&1 &
USERVER_PID=$!
echo "uvicorn PID: $USERVER_PID"
sleep 3

# Start cloudflared and capture URL
cloudflared tunnel --url http://127.0.0.1:$PORT >> "$LOG" 2>&1 &
CF_PID=$!
echo "cloudflared PID: $CF_PID"

# Wait for tunnel URL
sleep 8
URL=$(grep -o 'https://[^ ]*\.trycloudflare\.com' "$LOG" | tail -1)
echo "$URL" > "$URL_FILE"
echo ""
echo "========================================="
echo "Tunnel URL: $URL"
echo "Endpoint:   $URL/solve"
echo "Health:     $URL/health"
echo "========================================="
echo ""
echo "Submit at: https://app.ainm.no/submit/tripletex"

# Keep alive - restart if either dies
while true; do
    if ! kill -0 $USERVER_PID 2>/dev/null; then
        echo "uvicorn died, restarting..."
        uvicorn task2.solution:app --host 127.0.0.1 --port $PORT >> "$LOG" 2>&1 &
        USERVER_PID=$!
    fi
    if ! kill -0 $CF_PID 2>/dev/null; then
        echo "cloudflared died, restarting tunnel..."
        cloudflared tunnel --url http://127.0.0.1:$PORT >> "$LOG" 2>&1 &
        CF_PID=$!
        sleep 8
        URL=$(grep -o 'https://[^ ]*\.trycloudflare\.com' "$LOG" | tail -1)
        echo "New tunnel URL: $URL"
        echo "$URL" > "$URL_FILE"
    fi
    sleep 30
done
