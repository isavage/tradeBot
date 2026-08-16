#!/bin/sh
set -u

notify() {
  python -c "from src.notifications import send_ntfy; send_ntfy('$1', title='TradeBot ${MODE}')" || true
}

shutdown() {
  notify "TradeBot container stopped"
  exit 0
}

MODE="${1:-daily}"
INTERVAL=3600
[ "$MODE" = "intraday" ] && INTERVAL=900
trap shutdown TERM INT
notify "TradeBot ${MODE} container started"

while true; do
  python main.py --mode "$MODE"
  status=$?
  echo "TradeBot run exited with status $status"
  sleep "$INTERVAL" &
  wait $!
done
