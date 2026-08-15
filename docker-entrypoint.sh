#!/bin/sh
set -u

notify() {
  python -c "from src.notifications import send_ntfy; send_ntfy('$1', title='TradeBot container')" || true
}

shutdown() {
  notify "TradeBot container stopped"
  exit 0
}

trap shutdown TERM INT
notify "TradeBot container started"

while true; do
  python main.py
  status=$?
  echo "TradeBot run exited with status $status"
  sleep 3600 &
  wait $!
done
