# portfolio-tracker

Backs Marcus's 7:07am morning briefing Watchlist + Financials sections. Memory
(inside Claude) is the durable store for *what* to watch. This repo is the
disposable compute engine the briefing pulls fresh each morning to check
*whether* those watches have triggered.

## Files

- `portfolio_tracker.py` — main engine. Enriches a market snapshot against
  `portfolio_config.json` (your actual shares/cost basis) and evaluates
  `watch_rules.json` against it. Logs to `history.jsonl` so trend/momentum
  reflects real history, not one day's number.
- `portfolio_config.json` — your six standing holdings (BLK, AAPL, LMT, XOM,
  IAU, IBIT). Populated either by hand or via `schwab_client.py`.
- `watch_rules.json` — regenerated each morning by the briefing skill from
  your WATCHLIST memory lines. Not meant to be hand-maintained long-term —
  treat memory as the source of truth, this file as its daily compiled form.
- `schwab_client.py` — pulls live positions from Schwab's Trader API.
  **Run this on your own machine**, not from the scheduled task — it needs a
  real browser login and your app credentials, which stay local
  (`SCHWAB_APP_KEY` / `SCHWAB_APP_SECRET` env vars, never committed).
- `SKILL.md` — instructions for the Claude scheduled task: how to read/write
  watch requests to memory, run the engine each morning, and report results
  into the briefing without ever crossing into "you should buy/sell" territory.
- `history.jsonl` — append-only price log, one line per symbol per day.
  Commit this if you want the history to persist across environments; it's
  small (symbol/date/price only).

## What's NOT in this repo

Live Schwab tokens, Schwab app secrets, or any credential. `.schwab_token_cache.json`
(created locally by `schwab_client.py`) should be gitignored — it holds a
refresh token.

## Daily flow

1. Scheduled task pulls this repo fresh each morning.
2. Reads active WATCHLIST lines from memory, compiles them into `watch_rules.json`.
3. Gathers that day's prices/technicals for every watched + held symbol.
4. Runs `portfolio_tracker.py`, folds the output into the briefing.
5. Updates memory if a watch triggers or Marcus says to drop it.

See `SKILL.md` for the full step-by-step the scheduled task follows.
