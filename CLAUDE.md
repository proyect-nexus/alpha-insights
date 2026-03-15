# Insider Trading Detector — Agent Guide

## What is this

A web app that scans stock options (calls) across a curated 2,000-company global universe looking for unusual activity patterns that may indicate insider trading. It scores each anomaly 0-100 and cross-references with Reddit hype and earnings calendars for context (informational only, no score penalties).

**Stack**: Python 3.11+, FastAPI, yfinance, httpx, Tailwind CSS (CDN). No database — scans are saved as JSON files.

**Run**: `python app.py` → http://localhost:8000

## Architecture

```
app.py                → FastAPI server, routes, SSE streaming, scan persistence
scanner.py            → Core detection: fetches options chains, scores anomalies
context.py            → Reddit + earnings cross-referencing (async, httpx)
config.py             → All thresholds, weights, rate limits (single source of truth)
tickers.py            → Index definitions + insider universe loader
main.py               → CLI alternative (rich tables, --watch mode)
watchlist.json        → User-defined custom watchlists
insider_universe_tickers.json → 1993 companies by FactSet sector (generated)
insider_universe.json → Full universe data with ATR%, market cap, volume
build_universe.py     → Step 1: collect US tickers from Yahoo industries + screener
expand_universe.py    → Step 2: relax filters to expand US coverage
build_universe_global.py → Step 3: fill gaps with international tickers
universe_cache/       → Cached intermediate data for universe building
static/
  index.html          → SPA frontend (vanilla JS, Tailwind)
  how-it-works.html   → Documentation page
scans/                → Saved scan results as JSON (gitignored)
scheduled_scan.py     → GitHub Actions scan script
.github/workflows/    → Scheduled scans (3x daily) + email alerts
```

## Insider Universe (2,000 companies)

The scanner operates on a curated universe of ~1,993 companies filtered from global markets using sector-specific criteria. The universe is built by `build_universe_global.py` and stored in `insider_universe_tickers.json`.

### Universe composition

- **US**: 1,618 companies (81%) — primary market
- **International**: 375 companies (19%) — JP, GB, KR, CA, SE, HK, NL, FR, NO, DE, CH, IT, FI

### Sector filters (from insider_universe_filtros_completos.html)

Each FactSet sector has specific entry criteria:

| Sector | Tier | Target | Min Vol ($M) | Mkt Cap Range | ATR% 180d |
|---|---|---|---|---|---|
| Health Technology | T1 | 280 | 0.3 | $100M–$20B | ≥ 3% |
| Technology Services | T1 | 260 | 2.0 | $500M–$50B | 1–5% |
| Electronic Technology | T1 | 240 | 2.0 | $500M–$50B | 1–5% |
| Finance | T1 | 200 | 5.0 | $1B–$30B | 0.5–3% |
| Energy Minerals | T2 | 150 | 0.5 | $200M–$25B | 2–8% |
| Health Services | T2 | 120 | 0.3 | $100M–$15B | ≥ 2% |
| Consumer Non-Durables | T2 | 110 | 1.0 | $300M–$40B | 1–4% |
| Retail Trade | T2 | 100 | 1.0 | $300M–$40B | 1–4% |
| Producer Manufacturing | T2 | 90 | 1.0 | $300M–$30B | 1–4% |
| Consumer Durables | T3 | 80 | 1.0 | $400M–$35B | 1–5% |
| Industrial Services | T3 | 70 | 0.5 | $200M–$25B | 1–4% |
| Non-Energy Minerals | T3 | 65 | 0.5 | $200M–$20B | 2–7% |
| Consumer Services | T3 | 60 | 1.0 | $400M–$30B | 1–4% |
| Transportation | T3 | 55 | 0.5 | $300M–$25B | 1–4% |
| Process Industries | T3 | 50 | 0.5 | $200M–$20B | 1–4% |
| Commercial Services | T3 | 45 | 0.5 | $300M–$20B | 1–3% |
| Utilities | T3 | 40 | 1.0 | $500M–$25B | 0.5–2% |
| Communications | T4 | 30 | 1.0 | $500M–$30B | 0.5–3% |
| Distribution Services | T4 | 25 | 0.5 | $300M–$20B | 1–3% |
| Miscellaneous | T4 | 30 | 1.0 | $500M–$15B | ≥ 2% |

### How the universe is built

1. **`build_universe.py`**: Collects tickers from all ~145 Yahoo Finance industries (top 50 per industry) + paginated screener (US, mkt cap > $50M). Resolves industry → FactSet sector mapping. Downloads 1Y price data, computes ATR% 180d. Applies strict sector filters. Caches each step in `universe_cache/`.

2. **`expand_universe.py`**: Relaxes filters (wider mkt cap, wider ATR%, lower volume) to fill deficit sectors from existing data.

3. **`build_universe_global.py`**: Fills remaining gaps by searching international markets (CA, GB, DE, FR, JP, HK, KR, SE, etc.). US tickers are selected first with strict filters; international tickers only fill remaining slots.

### Rebuilding the universe

```bash
rm -rf universe_cache/  # clear caches to force fresh data
python build_universe_global.py  # takes ~40 min (rate limited by Yahoo Finance)
```

The universe is loaded at startup by `tickers.py` from `insider_universe_tickers.json`. Available as index `insider_universe` (full) or `insider_<sector>` (per sector).

## Data flow

1. User picks source (default: Insider Universe) → frontend calls `/api/scan/stream`
2. Backend iterates tickers, calls `scan_ticker()` for each → yfinance options chain
3. Each call option contract is filtered (min volume, DTE range, OTM range) then scored on 8 signals
4. Results streamed via SSE (`type: progress`, `type: alert`, `type: done`)
5. After scanning, `_enrich_with_context()` fetches Reddit mentions + earnings dates for tickers with alerts
6. Final results (alerts + insights + context) sent in the `done` event and saved to `scans/`

## Scoring (0-100)

Eight weighted signals (weights sum to 1.0), tuned for insider trading detection:

| Signal | Weight | What it measures |
|---|---|---|
| Notional ($) | 0.15 | Size of bet in dollars (vol × price × 100) |
| Near expiry | 0.15 | DTE — shorter = more leveraged = insiders know WHEN |
| OTM depth | 0.15 | How far out of the money — deep OTM = insiders buy cheap leverage |
| Vol/OI ratio | 0.13 | New positions — high ratio = fresh money entering |
| Vol vs baseline | 0.12 | Today's volume vs estimated daily normal (OI × 10%) |
| OI concentration | 0.12 | Abnormal OI concentrated in a single contract |
| Directional flow | 0.10 | Call/put volume ratio — extreme one-directional flow = conviction |
| Clustering | 0.08 | Multiple unusual contracts on same ticker |

Each signal normalized to 0-100, multiplied by weight, summed. See `scanner.py:_score()`.

### Weight rationale

The weights prioritize signals characteristic of insider trading:
- **OTM depth (0.15)**: Insiders buy deep OTM options because they're cheap and provide maximum leverage when you know the outcome.
- **Near expiry (0.15)**: Insiders know the timing of the catalyst, so they buy short-dated options.
- **Vol baseline (0.12, reduced)**: Pure volume spikes generate noise from retail activity; less weight reduces false positives.

### Directional flow

Scanner fetches both calls AND puts for each expiration. Calculates the percentage of volume in the dominant direction. 85%+ calls = extreme bullish flow, 85%+ puts = extreme bearish flow.

### OI concentration

Detects when a single contract holds 20%+ of the ticker's total OI with at least 1,000 contracts. This indicates deliberate accumulation in a specific strike/expiration.

## Context system (context.py)

- **Reddit**: Searches r/wallstreetbets, r/stocks, r/options, r/investing, r/stockmarket + global search. Uses `Accept-Language: en-US` for English results. Classifies hype as none/low/moderate/high/viral.
- **Earnings**: Checks yfinance calendar for upcoming earnings dates within 30 days.
- **No penalties**: Reddit and earnings data is purely informational. No score adjustments are applied. Context is displayed in the UI for analyst review but does not affect the score.
- All context data (posts, dates, links) is saved in scan JSONs for posterior analysis.

## Key design decisions

- **Reddit does NOT penalize scores** — it's informational context only. A ticker trending on Reddit can still be genuine insider trading.
- **Earnings do NOT penalize** — pre-earnings unusual activity is exactly the insider trading pattern we're looking for.
- **Default scan source is Insider Universe** — the curated 1,993-company list, not watchlists.
- **SSE streaming** is required for index scans (500+ tickers). Uses `await asyncio.sleep()` for rate limiting — never `time.sleep()` in async context.
- **All data is persisted** in scan JSONs including Reddit posts, earnings dates, raw scores.
- **Modal shows all Reddit articles** with links, subreddit, upvotes, comments, and relative publication time.

## Scheduled scans (GitHub Actions)

The workflow `.github/workflows/scheduled-scan.yml` runs 3 times daily on weekdays:
- 16:30 Madrid (14:30 UTC) — mid US session
- 19:00 Madrid (17:00 UTC) — near US close
- 21:30 Madrid (19:30 UTC) — after hours

### What it scans

`scheduled_scan.py` calls `collect_all_tickers()` which combines ALL indices (including the full insider universe). Total: ~2,412 unique tickers.

### Email alerts

Email is sent via Resend API when any ticker scores **>= 50** (configurable in `scheduled_scan.py:build_email_body()`). The email includes ticker, company, score, notional, and top contract details. Requires `RESEND_API_KEY`, `RESEND_FROM`, and `ALERT_EMAILS` secrets in GitHub.

## API routes

| Method | Path | Description |
|---|---|---|
| GET | `/` | Main SPA |
| GET | `/how-it-works` | Documentation page |
| GET | `/api/indices` | Available indices + ticker counts |
| GET | `/api/watchlist` | Custom watchlists |
| POST | `/api/watchlist/{name}` | Create/update watchlist |
| DELETE | `/api/watchlist/{name}` | Delete watchlist |
| GET | `/api/scan` | Scan (blocking, for small lists) |
| GET | `/api/scan/stream` | Scan with SSE streaming |
| GET | `/api/scan/full` | Full scan: all indices combined, SSE |
| GET | `/api/context/{ticker}` | Reddit + earnings context for one ticker |
| GET | `/api/history` | List saved scans |
| GET | `/api/history/{filename}` | Load a saved scan |
| DELETE | `/api/history/{filename}` | Delete a saved scan |
| GET | `/api/trends` | Trend analysis across scheduled scans |
| GET | `/api/market/fear-greed` | Fear & Greed index data |
| GET | `/api/market/sector-heatmap` | Sector ETF heatmap |

## Common scan parameters

- `threshold` (int, default 50): minimum score to generate alert
- `list` (str): watchlist name
- `index` (str): index key from tickers.py (insider_universe, nasdaq100, sp500, etc.)
- `tickers` (str): comma-separated ticker symbols
- `top` (int, default 30): for full scan, how many top companies to return

## Modifying thresholds

All detection parameters are in `config.py`. Change weights, minimums, rate limits there. The scoring formula is in `scanner.py:_score()`.

## Rate limiting

Yahoo Finance is rate-sensitive. Config defaults: 0.3s between tickers, 2.0s every 10 tickers. Adjust in `config.py` if getting throttled.

## Frontend

Single HTML file (`static/index.html`) with inline JS. No build step. Uses Tailwind CDN.

- Default source: **Indice → Insider Universe (Full)**
- Insider indices appear first in the dropdown, followed by standard indices
- Key globals: `allAlerts`, `scanData`
- SSE `done` event includes enriched `alerts` array — frontend replaces accumulated alerts with it
- Modal opens on click of insight card or table row, closes on Escape or click outside
