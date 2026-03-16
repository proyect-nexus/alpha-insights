"""
Market KPIs: CNN Fear & Greed index and Sector ETF heatmap.
"""

import asyncio
from datetime import datetime, timedelta
import time

import httpx
import yfinance as yf


# Cache TTL: 15 minutes
_cache = {}
_CACHE_TTL = 900


def _cached(key: str):
    """Simple TTL cache check."""
    if key in _cache:
        data, ts = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    return None


def _set_cache(key: str, data):
    _cache[key] = (data, time.time())


# --- Fear & Greed (CNN data) ---
_CNN_INDICATOR_LABELS = {
    "market_momentum_sp500": "Market Momentum (S&P 500)",
    "stock_price_strength": "Stock Price Strength",
    "stock_price_breadth": "Stock Price Breadth",
    "put_call_options": "Put/Call Options",
    "market_volatility_vix": "Market Volatility (VIX)",
    "junk_bond_demand": "Junk Bond Demand",
    "safe_haven_demand": "Safe Haven Demand",
}


def _fetch_cnn_fear_greed() -> dict:
    """Fetch real Fear & Greed data from CNN."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    r = httpx.get(
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    fg = data.get("fear_and_greed", {})
    score = round(fg.get("score", 50))
    rating = fg.get("rating", "neutral")

    # Map rating to our labels
    label_map = {
        "extreme fear": "Extreme Fear",
        "fear": "Fear",
        "neutral": "Neutral",
        "greed": "Greed",
        "extreme greed": "Extreme Greed",
    }
    label = label_map.get(rating, rating.title())

    # Extract individual indicators
    signals = {}
    for key, display_label in _CNN_INDICATOR_LABELS.items():
        indicator = data.get(key, {})
        if isinstance(indicator, dict) and "score" in indicator:
            signals[key] = {
                "score": round(indicator["score"]),
                "rating": indicator.get("rating", ""),
                "label": display_label,
            }

    # Historical comparison
    history = {
        "previous_close": round(fg.get("previous_close", 0)),
        "previous_1_week": round(fg.get("previous_1_week", 0)),
        "previous_1_month": round(fg.get("previous_1_month", 0)),
        "previous_1_year": round(fg.get("previous_1_year", 0)),
    }

    return {
        "score": score,
        "label": label,
        "signals": signals,
        "history": history,
        "timestamp": fg.get("timestamp", ""),
        "updated": datetime.now().isoformat(),
        "source": "CNN Fear & Greed Index",
    }


async def get_fear_and_greed() -> dict:
    cached = _cached("fear_greed")
    if cached:
        return cached
    try:
        result = await asyncio.to_thread(_fetch_cnn_fear_greed)
    except Exception as e:
        return {"score": 0, "label": "Error", "signals": {}, "error": str(e)}
    _set_cache("fear_greed", result)
    return result


# --- Sector ETF Heatmap ---
SECTOR_ETFS = {
    "XLK": "Technology",
    "XLV": "Healthcare",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Disc.",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "XLB": "Materials",
    "XLC": "Communication",
}


VALID_PERIODS = {"1mo", "3mo", "6mo", "1y"}


def _compute_sector_heatmap(period: str = "1mo") -> dict:
    """Compute sector ETF heatmap based on price performance and volume change."""
    sectors = []
    min_bars = {"1mo": 10, "3mo": 30, "6mo": 60, "1y": 100}

    for symbol, name in SECTOR_ETFS.items():
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=period)
            if len(hist) < min_bars.get(period, 10):
                continue

            # Volume change: recent 20% of bars vs earlier 80%
            split = max(5, len(hist) // 5)
            recent = hist.tail(split)
            earlier = hist.head(len(hist) - split)

            avg_vol_recent = float(recent["Volume"].mean())
            avg_vol_earlier = float(earlier["Volume"].mean())

            vol_change = ((avg_vol_recent - avg_vol_earlier) / avg_vol_earlier * 100) if avg_vol_earlier > 0 else 0

            # Price change over the full period
            price_start = float(hist["Close"].iloc[0])
            price_end = float(hist["Close"].iloc[-1])
            price_change = ((price_end - price_start) / price_start) * 100

            current_price = round(price_end, 2)

            sectors.append({
                "symbol": symbol,
                "name": name,
                "price": current_price,
                "price_change": round(price_change, 2),
                "vol_change": round(vol_change, 2),
            })
        except Exception:
            continue

    sectors.sort(key=lambda x: x["price_change"], reverse=True)

    return {
        "period": period,
        "sectors": sectors,
        "updated": datetime.now().isoformat(),
    }


async def get_sector_heatmap(period: str = "1mo") -> dict:
    if period not in VALID_PERIODS:
        period = "1mo"
    cache_key = f"sector_heatmap_{period}"
    cached = _cached(cache_key)
    if cached:
        return cached
    result = await asyncio.to_thread(_compute_sector_heatmap, period)
    _set_cache(cache_key, result)
    return result
