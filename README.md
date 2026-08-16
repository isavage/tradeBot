# TradeBot

Regime-aware Alpaca market scanner for daily and intraday momentum signals. It is configured for paper trading; order submission is disabled by default.

## Strategies

Daily mode stores four years of daily Parquet history for backtesting, but uses only the latest 300 candles for live calculations. It evaluates once per trading day at or after market open using the previous completed daily candle. Alpaca's calendar handles weekends, holidays, and early closes.

Intraday mode uses current-session 1-minute bars, stores them in `data/intraday/<SYMBOL>.parquet`, and appends only new bars during the session. Files are replaced on the next trading day. It evaluates every 15 minutes from 10:30 AM through 2:00 PM Eastern Time.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env`:

```env
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
NTFY_URL=https://ntfy.sh
NTFY_TOPIC=some-long-random-private-topic
```

Install the ntfy mobile app and subscribe to the same topic. Alerts cover candidates, failures, and container start/stop events. Notifications are skipped when `NTFY_TOPIC` is unset.

Run locally:

```bash
python main.py --mode daily
python main.py --mode intraday
python monitor_positions.py
python backtest.py --side bullish --horizon 20 --output results/bullish.csv
./.venv/bin/python -m pytest -q
```

## Docker

One image runs independent daily and intraday services:

```bash
docker compose up -d --build
docker compose logs -f daily
docker compose logs -f intraday
```

VPS bind mounts:

```text
/docker/tradebot/data  -> /app/data
/docker/tradebot/logs  -> /app/logs
```

The container wrapper handles service loops and lifecycle notifications.

## VPS deployment

`.github/workflows/deploy.yml` deploys to `/docker/tradebot` and uses the GitHub `prod-IN` environment by default. Required environment secrets are:

```text
VPS_HOST
VPS_USER
VPS_SSH_KEY
DOPPLER_TOKEN
```

Doppler supplies Alpaca and ntfy variables to Docker Compose on the VPS. Local `.env` is the development fallback. Secret files are excluded from deployment.

## Configuration and layout

Runtime settings are in `config/config.yaml`, including data feed, universe discovery, daily and intraday thresholds, trading windows, risk, options, exits, and execution safety.

```text
main.py                 daily/intraday CLI
backtest.py             historical underlying-signal backtest
monitor_positions.py    position-monitor entry point
src/                    reusable application modules
config/config.yaml      runtime configuration
Dockerfile              shared image
docker-compose.yml      daily and intraday services
docker-entrypoint.sh    service loop and lifecycle alerts
```

## Safety

This project is not financial advice. Before enabling orders, add and validate position reconciliation, buying-power checks, persisted trade metadata, option spread validation, and a tested daily-loss circuit breaker.
