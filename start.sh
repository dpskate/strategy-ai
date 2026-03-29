#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
UVICORN="/Users/dpskate/Library/Python/3.9/bin/uvicorn"
NPM="/opt/homebrew/bin/npm"

cleanup() {
    echo "Stopping strategy-ai..."
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
    wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR"
"$UVICORN" api:app --host 127.0.0.1 --port 8100 &
BACKEND_PID=$!
echo "Backend:  http://localhost:8100"

cd "$PROJECT_DIR/web"
"$NPM" run dev -- --port 3000 &
FRONTEND_PID=$!
echo "Frontend: http://localhost:3000"

echo "Press Ctrl+C to stop."
wait "$BACKEND_PID" "$FRONTEND_PID"
