#!/usr/bin/env bash
# Forward collection for the registered sparse-entry family. Read-only market data; never trades.
#
#   services/otc_sparse_prereg/collect.sh live       # start the live harvester (restarts on crash)
#   services/otc_sparse_prereg/collect.sh backfill   # history-API candles before an evaluation look
#   services/otc_sparse_prereg/collect.sh status     # health line, appended to data/forward/progress.log
#   services/otc_sparse_prereg/collect.sh stop
#
# Credentials: IQ_EMAIL / IQ_PASSWORD are loaded from the repo .env inside Python, never on argv.
set -euo pipefail
cd "$(dirname "$0")/../.."
ROOT=$(pwd)
PY="$ROOT/venv/bin/python"
LAB="$ROOT/.venv-lab/bin/python"
DIR="$ROOT/data/forward"
DB="$DIR/sparse_forward.sqlite"
PIDFILE="$DIR/live.pid"
mkdir -p "$DIR"
ASSETS="EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC,AUDUSD-OTC,NZDUSD-OTC,USDCAD-OTC,USDCHF-OTC,EURGBP-OTC,EURJPY-OTC,GBPJPY-OTC,EURAUD-OTC,GBPAUD-OTC,AUDJPY-OTC,CHFJPY-OTC,CADJPY-OTC"

harvest() {  # loads .env in-process, then runs the harvester module with the given flags
  "$PY" - "$@" <<'EOF'
import os, runpy, sys
from dotenv import dotenv_values
env = dotenv_values(os.path.join(os.getcwd(), ".env"))
for key in ("IQ_EMAIL", "IQ_PASSWORD"):
    if not env.get(key):
        sys.exit(f"missing {key} in .env")
    os.environ[key] = env[key]
sys.argv = ["harvest_market_data"] + sys.argv[1:]
runpy.run_module("trading_platform.scripts.harvest_market_data", run_name="__main__")
EOF
}

"$LAB" -m services.otc_sparse_prereg.run verify >/dev/null || { echo "registration does not verify; refusing" >&2; exit 2; }

case "${1:-}" in
  live)
    if [[ -f "$PIDFILE" ]] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "already running: $(cat "$PIDFILE")"; exit 0; fi
    (
      while true; do
        harvest --mode live --db "$DB" --assets "$ASSETS" --payout-interval-seconds 30 \
          --mood-interval-seconds 5 --live-timeframes 1,120,300 --no-binary-deals --account-type PRACTICE \
          >>"$DIR/harvester.log" 2>&1 || true
        [[ -f "$DIR/stop" ]] && break
        echo "$(date -u +%FT%TZ) harvester exited; restarting in 30 s" >>"$DIR/harvester.log"
        sleep 30
      done
    ) &
    echo $! >"$PIDFILE"
    rm -f "$DIR/stop"
    echo "live harvester supervisor pid $(cat "$PIDFILE"); log $DIR/harvester.log"
    echo "follow progress: tail -f $DIR/progress.log"
    ;;
  backfill)
    START=$("$LAB" -c "from services.otc_sparse_prereg import spec; print(spec.FORWARD_START_MS)")
    DAYS=$(( ( $(date +%s) * 1000 - START ) / 86400000 + 3 ))
    harvest --mode backfill --db "$DB" --assets "$ASSETS" --history-timeframes 120,300 --history-days "$DAYS" \
      >>"$DIR/harvester.log" 2>&1
    ;;
  status)
    "$LAB" -m services.otc_sparse_prereg.run status --forward-db "$DB" --progress-log "$DIR/progress.log"
    ;;
  stop)
    touch "$DIR/stop"
    if [[ -f "$PIDFILE" ]]; then pkill -TERM -P "$(cat "$PIDFILE")" 2>/dev/null || true; kill "$(cat "$PIDFILE")" 2>/dev/null || true; rm -f "$PIDFILE"; fi
    echo stopped
    ;;
  *) echo "usage: $0 live|backfill|status|stop" >&2; exit 64 ;;
esac
