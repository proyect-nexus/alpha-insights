"""
Expand the insider universe to reach ~2,000 companies.
1. Load cached data from build_universe.py
2. For deficit sectors, search for MORE tickers via screener (sector-filtered)
3. Progressively relax filters until target is met
4. Download ATR for new tickers
"""

import json
import time
import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path

CACHE_DIR = Path("universe_cache")

# ── Original filters (from build_universe.py) ───────────────────────────────
SECTOR_FILTERS = {
    "Health Technology":      {"n": 280, "min_vol_M": 0.3, "min_cap_M": 100,  "max_cap_B": 20,  "atr_min": 3.0, "atr_max": 999},
    "Technology Services":    {"n": 260, "min_vol_M": 2.0, "min_cap_M": 500,  "max_cap_B": 50,  "atr_min": 1.0, "atr_max": 5.0},
    "Electronic Technology":  {"n": 240, "min_vol_M": 2.0, "min_cap_M": 500,  "max_cap_B": 50,  "atr_min": 1.0, "atr_max": 5.0},
    "Finance":                {"n": 200, "min_vol_M": 5.0, "min_cap_M": 1000, "max_cap_B": 30,  "atr_min": 0.5, "atr_max": 3.0},
    "Energy Minerals":        {"n": 150, "min_vol_M": 0.5, "min_cap_M": 200,  "max_cap_B": 25,  "atr_min": 2.0, "atr_max": 8.0},
    "Health Services":        {"n": 120, "min_vol_M": 0.3, "min_cap_M": 100,  "max_cap_B": 15,  "atr_min": 2.0, "atr_max": 999},
    "Consumer Non-Durables":  {"n": 110, "min_vol_M": 1.0, "min_cap_M": 300,  "max_cap_B": 40,  "atr_min": 1.0, "atr_max": 4.0},
    "Retail Trade":           {"n": 100, "min_vol_M": 1.0, "min_cap_M": 300,  "max_cap_B": 40,  "atr_min": 1.0, "atr_max": 4.0},
    "Producer Manufacturing": {"n": 90,  "min_vol_M": 1.0, "min_cap_M": 300,  "max_cap_B": 30,  "atr_min": 1.0, "atr_max": 4.0},
    "Consumer Durables":      {"n": 80,  "min_vol_M": 1.0, "min_cap_M": 400,  "max_cap_B": 35,  "atr_min": 1.0, "atr_max": 5.0},
    "Industrial Services":    {"n": 70,  "min_vol_M": 0.5, "min_cap_M": 200,  "max_cap_B": 25,  "atr_min": 1.0, "atr_max": 4.0},
    "Non-Energy Minerals":    {"n": 65,  "min_vol_M": 0.5, "min_cap_M": 200,  "max_cap_B": 20,  "atr_min": 2.0, "atr_max": 7.0},
    "Consumer Services":      {"n": 60,  "min_vol_M": 1.0, "min_cap_M": 400,  "max_cap_B": 30,  "atr_min": 1.0, "atr_max": 4.0},
    "Transportation":         {"n": 55,  "min_vol_M": 0.5, "min_cap_M": 300,  "max_cap_B": 25,  "atr_min": 1.0, "atr_max": 4.0},
    "Process Industries":     {"n": 50,  "min_vol_M": 0.5, "min_cap_M": 200,  "max_cap_B": 20,  "atr_min": 1.0, "atr_max": 4.0},
    "Commercial Services":    {"n": 45,  "min_vol_M": 0.5, "min_cap_M": 300,  "max_cap_B": 20,  "atr_min": 1.0, "atr_max": 3.0},
    "Utilities":              {"n": 40,  "min_vol_M": 1.0, "min_cap_M": 500,  "max_cap_B": 25,  "atr_min": 0.5, "atr_max": 2.0},
    "Communications":         {"n": 30,  "min_vol_M": 1.0, "min_cap_M": 500,  "max_cap_B": 30,  "atr_min": 0.5, "atr_max": 3.0},
    "Distribution Services":  {"n": 25,  "min_vol_M": 0.5, "min_cap_M": 300,  "max_cap_B": 20,  "atr_min": 1.0, "atr_max": 3.0},
    "Miscellaneous":          {"n": 30,  "min_vol_M": 1.0, "min_cap_M": 500,  "max_cap_B": 15,  "atr_min": 2.0, "atr_max": 999},
}

# ── Relaxed filters: widen cap range, widen ATR, lower volume ───────────────
RELAXED_FILTERS = {
    "Health Technology":      {"min_vol_M": 0.1, "min_cap_M": 50,   "max_cap_B": 40,  "atr_min": 2.0, "atr_max": 999},
    "Technology Services":    {"min_vol_M": 0.5, "min_cap_M": 200,  "max_cap_B": 150, "atr_min": 0.5, "atr_max": 8.0},
    "Electronic Technology":  {"min_vol_M": 0.5, "min_cap_M": 200,  "max_cap_B": 200, "atr_min": 0.5, "atr_max": 8.0},
    "Finance":                {"min_vol_M": 1.0, "min_cap_M": 300,  "max_cap_B": 80,  "atr_min": 0.3, "atr_max": 5.0},
    "Energy Minerals":        {"min_vol_M": 0.2, "min_cap_M": 100,  "max_cap_B": 50,  "atr_min": 1.5, "atr_max": 12.0},
    "Health Services":        {"min_vol_M": 0.1, "min_cap_M": 50,   "max_cap_B": 80,  "atr_min": 1.0, "atr_max": 999},
    "Consumer Non-Durables":  {"min_vol_M": 0.3, "min_cap_M": 100,  "max_cap_B": 80,  "atr_min": 0.5, "atr_max": 6.0},
    "Retail Trade":           {"min_vol_M": 0.3, "min_cap_M": 100,  "max_cap_B": 80,  "atr_min": 0.5, "atr_max": 6.0},
    "Producer Manufacturing": {"min_vol_M": 0.3, "min_cap_M": 100,  "max_cap_B": 60,  "atr_min": 0.5, "atr_max": 6.0},
    "Consumer Durables":      {"min_vol_M": 0.3, "min_cap_M": 100,  "max_cap_B": 60,  "atr_min": 0.5, "atr_max": 8.0},
    "Industrial Services":    {"min_vol_M": 0.2, "min_cap_M": 100,  "max_cap_B": 50,  "atr_min": 0.5, "atr_max": 6.0},
    "Non-Energy Minerals":    {"min_vol_M": 0.2, "min_cap_M": 100,  "max_cap_B": 40,  "atr_min": 1.0, "atr_max": 12.0},
    "Consumer Services":      {"min_vol_M": 0.3, "min_cap_M": 100,  "max_cap_B": 60,  "atr_min": 0.5, "atr_max": 6.0},
    "Transportation":         {"min_vol_M": 0.2, "min_cap_M": 100,  "max_cap_B": 60,  "atr_min": 0.5, "atr_max": 6.0},
    "Process Industries":     {"min_vol_M": 0.2, "min_cap_M": 100,  "max_cap_B": 40,  "atr_min": 0.5, "atr_max": 6.0},
    "Commercial Services":    {"min_vol_M": 0.2, "min_cap_M": 100,  "max_cap_B": 40,  "atr_min": 0.5, "atr_max": 5.0},
    "Utilities":              {"min_vol_M": 0.3, "min_cap_M": 200,  "max_cap_B": 60,  "atr_min": 0.3, "atr_max": 4.0},
    "Communications":         {"min_vol_M": 0.3, "min_cap_M": 200,  "max_cap_B": 80,  "atr_min": 0.3, "atr_max": 5.0},
    "Distribution Services":  {"min_vol_M": 0.2, "min_cap_M": 100,  "max_cap_B": 40,  "atr_min": 0.5, "atr_max": 5.0},
    "Miscellaneous":          {"min_vol_M": 0.3, "min_cap_M": 200,  "max_cap_B": 40,  "atr_min": 1.0, "atr_max": 999},
}

# Yahoo industry → FactSet sector (same as build_universe.py)
INDUSTRY_TO_SECTOR = {
    "biotechnology": "Health Technology", "drug-manufacturers-general": "Health Technology",
    "drug-manufacturers-specialty-generic": "Health Technology", "medical-devices": "Health Technology",
    "diagnostics-research": "Health Technology", "medical-instruments-supplies": "Health Technology",
    "health-information-services": "Health Technology",
    "healthcare-plans": "Health Services", "medical-care-facilities": "Health Services",
    "medical-distribution": "Health Services", "pharmaceutical-retailers": "Health Services",
    "software-infrastructure": "Technology Services", "software-application": "Technology Services",
    "information-technology-services": "Technology Services",
    "semiconductors": "Electronic Technology", "semiconductor-equipment-materials": "Electronic Technology",
    "consumer-electronics": "Electronic Technology", "computer-hardware": "Electronic Technology",
    "communication-equipment": "Electronic Technology", "electronic-components": "Electronic Technology",
    "scientific-technical-instruments": "Electronic Technology", "solar": "Electronic Technology",
    "electronics-computer-distribution": "Electronic Technology",
    "banks-diversified": "Finance", "credit-services": "Finance", "asset-management": "Finance",
    "insurance-diversified": "Finance", "capital-markets": "Finance", "banks-regional": "Finance",
    "financial-data-stock-exchanges": "Finance", "insurance-property-casualty": "Finance",
    "insurance-brokers": "Finance", "insurance-life": "Finance", "insurance-specialty": "Finance",
    "mortgage-finance": "Finance", "insurance-reinsurance": "Finance",
    "financial-conglomerates": "Finance", "shell-companies": "Finance",
    "oil-gas-integrated": "Energy Minerals", "oil-gas-midstream": "Energy Minerals",
    "oil-gas-e-p": "Energy Minerals", "oil-gas-equipment-services": "Energy Minerals",
    "oil-gas-refining-marketing": "Energy Minerals", "uranium": "Energy Minerals",
    "oil-gas-drilling": "Energy Minerals", "thermal-coal": "Energy Minerals",
    "discount-stores": "Consumer Non-Durables", "beverages-non-alcoholic": "Consumer Non-Durables",
    "household-personal-products": "Consumer Non-Durables", "tobacco": "Consumer Non-Durables",
    "packaged-foods": "Consumer Non-Durables", "confectioners": "Consumer Non-Durables",
    "farm-products": "Consumer Non-Durables", "food-distribution": "Consumer Non-Durables",
    "grocery-stores": "Consumer Non-Durables", "beverages-brewers": "Consumer Non-Durables",
    "education-training-services": "Consumer Non-Durables",
    "beverages-wineries-distilleries": "Consumer Non-Durables",
    "internet-retail": "Retail Trade", "home-improvement-retail": "Retail Trade",
    "apparel-retail": "Retail Trade", "specialty-retail": "Retail Trade",
    "auto-truck-dealerships": "Retail Trade", "department-stores": "Retail Trade",
    "auto-manufacturers": "Consumer Durables", "auto-parts": "Consumer Durables",
    "residential-construction": "Consumer Durables", "packaging-containers": "Consumer Durables",
    "furnishings-fixtures-appliances": "Consumer Durables", "recreational-vehicles": "Consumer Durables",
    "footwear-accessories": "Consumer Durables", "luxury-goods": "Consumer Durables",
    "textile-manufacturing": "Consumer Durables", "apparel-manufacturing": "Consumer Durables",
    "restaurants": "Consumer Services", "travel-services": "Consumer Services",
    "lodging": "Consumer Services", "resorts-casinos": "Consumer Services",
    "leisure": "Consumer Services", "gambling": "Consumer Services",
    "personal-services": "Consumer Services",
    "aerospace-defense": "Producer Manufacturing",
    "specialty-industrial-machinery": "Producer Manufacturing",
    "farm-heavy-construction-machinery": "Producer Manufacturing",
    "building-products-equipment": "Producer Manufacturing",
    "electrical-equipment-parts": "Producer Manufacturing",
    "tools-accessories": "Producer Manufacturing", "metal-fabrication": "Producer Manufacturing",
    "conglomerates": "Producer Manufacturing",
    "engineering-construction": "Industrial Services",
    "pollution-treatment-controls": "Industrial Services",
    "infrastructure-operations": "Industrial Services",
    "railroads": "Transportation", "integrated-freight-logistics": "Transportation",
    "airlines": "Transportation", "trucking": "Transportation",
    "marine-shipping": "Transportation", "airports-air-services": "Transportation",
    "specialty-business-services": "Commercial Services", "waste-management": "Commercial Services",
    "rental-leasing-services": "Commercial Services", "consulting-services": "Commercial Services",
    "security-protection-services": "Commercial Services",
    "staffing-employment-services": "Commercial Services",
    "business-equipment-supplies": "Commercial Services",
    "industrial-distribution": "Distribution Services",
    "gold": "Non-Energy Minerals", "copper": "Non-Energy Minerals", "steel": "Non-Energy Minerals",
    "other-industrial-metals-mining": "Non-Energy Minerals",
    "other-precious-metals-mining": "Non-Energy Minerals", "aluminum": "Non-Energy Minerals",
    "silver": "Non-Energy Minerals", "building-materials": "Non-Energy Minerals",
    "coking-coal": "Non-Energy Minerals",
    "specialty-chemicals": "Process Industries", "agricultural-inputs": "Process Industries",
    "chemicals": "Process Industries", "lumber-wood-production": "Process Industries",
    "paper-paper-products": "Process Industries",
    "utilities-regulated-electric": "Utilities",
    "utilities-independent-power-producers": "Utilities",
    "utilities-regulated-gas": "Utilities", "utilities-diversified": "Utilities",
    "utilities-renewable": "Utilities", "utilities-regulated-water": "Utilities",
    "internet-content-information": "Communications", "telecom-services": "Communications",
    "entertainment": "Communications", "advertising-agencies": "Communications",
    "electronic-gaming-multimedia": "Communications", "publishing": "Communications",
    "broadcasting": "Communications",
    "reit-specialty": "Miscellaneous", "reit-industrial": "Miscellaneous",
    "reit-healthcare-facilities": "Miscellaneous", "reit-retail": "Miscellaneous",
    "reit-residential": "Miscellaneous", "real-estate-services": "Miscellaneous",
    "reit-mortgage": "Miscellaneous", "reit-diversified": "Miscellaneous",
    "reit-office": "Miscellaneous", "reit-hotel-motel": "Miscellaneous",
    "real-estate-development": "Miscellaneous", "real-estate-diversified": "Miscellaneous",
}

YAHOO_SECTOR_FALLBACK = {
    "Healthcare": "Health Technology", "Technology": "Technology Services",
    "Financial Services": "Finance", "Energy": "Energy Minerals",
    "Consumer Defensive": "Consumer Non-Durables", "Consumer Cyclical": "Consumer Durables",
    "Industrials": "Producer Manufacturing", "Basic Materials": "Non-Energy Minerals",
    "Utilities": "Utilities", "Communication Services": "Communications",
    "Real Estate": "Miscellaneous",
}

# FactSet sector → Yahoo screener sector values for targeted search
FACTSET_TO_YAHOO_SECTORS = {
    "Health Technology": ["Healthcare"],
    "Health Services": ["Healthcare"],
    "Technology Services": ["Technology"],
    "Electronic Technology": ["Technology"],
    "Finance": ["Financial Services"],
    "Energy Minerals": ["Energy"],
    "Consumer Non-Durables": ["Consumer Defensive"],
    "Retail Trade": ["Consumer Cyclical"],
    "Consumer Durables": ["Consumer Cyclical"],
    "Consumer Services": ["Consumer Cyclical"],
    "Producer Manufacturing": ["Industrials"],
    "Industrial Services": ["Industrials"],
    "Transportation": ["Industrials"],
    "Commercial Services": ["Industrials"],
    "Distribution Services": ["Industrials"],
    "Non-Energy Minerals": ["Basic Materials"],
    "Process Industries": ["Basic Materials"],
    "Utilities": ["Utilities"],
    "Communications": ["Communication Services"],
    "Miscellaneous": ["Real Estate"],
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_caches():
    """Load all cached data from build_universe.py."""
    industry_tickers = json.loads((CACHE_DIR / "industry_tickers.json").read_text())
    screener_data = json.loads((CACHE_DIR / "screener_tickers.json").read_text())
    resolved = json.loads((CACHE_DIR / "resolved_industries.json").read_text())
    atr_data = json.loads((CACHE_DIR / "atr_data.json").read_text())

    # Merge industry maps
    ticker_map = {**industry_tickers, **resolved}
    return ticker_map, screener_data, atr_data


def search_sector_tickers(yahoo_sector, min_cap, max_cap, existing_syms):
    """Use screener to find tickers in a specific Yahoo sector."""
    new_tickers = {}
    try:
        q = yf.EquityQuery('and', [
            yf.EquityQuery('eq', ['region', 'us']),
            yf.EquityQuery('eq', ['sector', yahoo_sector]),
            yf.EquityQuery('gt', ['intradaymarketcap', min_cap]),
            yf.EquityQuery('lt', ['intradaymarketcap', max_cap]),
            yf.EquityQuery('gt', ['avgdailyvol3m', 30000]),
        ])
        offset = 0
        while True:
            result = yf.screen(q, size=250, offset=offset)
            quotes = result.get('quotes', [])
            if not quotes:
                break
            for qt in quotes:
                sym = qt.get('symbol', '')
                if sym and sym not in existing_syms:
                    new_tickers[sym] = {
                        "marketCap": qt.get("marketCap", 0),
                        "avgVolume": qt.get("averageDailyVolume3Month", 0),
                        "price": qt.get("regularMarketPrice", 0),
                        "name": qt.get("longName") or qt.get("shortName", ""),
                    }
            offset += 250
            if offset >= result.get('total', 0):
                break
            time.sleep(0.3)
    except Exception as e:
        log(f"    Screener error for {yahoo_sector}: {e}")
    return new_tickers


def resolve_industry_batch(symbols):
    """Get industry info for a batch of symbols."""
    results = {}
    for sym in symbols:
        try:
            info = yf.Ticker(sym).info
            ind_key = info.get("industryKey", "")
            sector = info.get("sector", "")
            factset = INDUSTRY_TO_SECTOR.get(ind_key)
            if not factset and sector:
                factset = YAHOO_SECTOR_FALLBACK.get(sector)
            if factset:
                results[sym] = {
                    "industry_key": ind_key,
                    "factset_sector": factset,
                    "name": info.get("longName") or info.get("shortName", ""),
                }
        except Exception:
            pass
        time.sleep(0.12)
    return results


def compute_atr_batch(symbols, existing_atr):
    """Compute ATR for new symbols not in existing_atr."""
    new_syms = [s for s in symbols if s not in existing_atr]
    if not new_syms:
        return {}

    log(f"  Downloading ATR data for {len(new_syms)} new tickers...")
    results = {}
    batch_size = 100
    for i in range(0, len(new_syms), batch_size):
        batch = new_syms[i:i+batch_size]
        try:
            data = yf.download(" ".join(batch), period="1y", progress=False, threads=True)
            if data.empty:
                continue
            for sym in batch:
                try:
                    if len(batch) == 1:
                        high, low, close, vol = data["High"], data["Low"], data["Close"], data["Volume"]
                    else:
                        high, low, close, vol = data["High"][sym], data["Low"][sym], data["Close"][sym], data["Volume"][sym]
                    high, low, close = high.dropna(), low.dropna(), close.dropna()
                    if len(close) < 60:
                        continue
                    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
                    lookback = min(180, len(tr))
                    atr_180 = tr.tail(lookback).mean()
                    avg_close_180 = close.tail(lookback).mean()
                    atr_pct_180 = (atr_180 / avg_close_180 * 100) if avg_close_180 > 0 else 0
                    atr_30 = tr.tail(30).mean()
                    avg_close_30 = close.tail(30).mean()
                    atr_pct_30 = (atr_30 / avg_close_30 * 100) if avg_close_30 > 0 else 0
                    avg_dollar_vol = (vol.tail(30).dropna() * close.tail(30).dropna()).mean()
                    results[sym] = {
                        "atr_pct_180d": round(float(atr_pct_180), 3),
                        "atr_pct_30d": round(float(atr_pct_30), 3),
                        "avg_dollar_vol_30d": round(float(avg_dollar_vol), 0),
                        "last_close": round(float(close.iloc[-1]), 2),
                    }
                except Exception:
                    pass
        except Exception as e:
            log(f"    Download error: {e}")
        time.sleep(0.5)
    log(f"  Got ATR for {len(results)} new tickers")
    return results


def apply_filters(all_tickers, screener_data, atr_data, filters_dict):
    """Apply filters and return selected tickers per sector."""
    universe = {}
    stats = {}
    for sector_name, filters in filters_dict.items():
        candidates = []
        for sym, info in all_tickers.items():
            if info["factset_sector"] != sector_name:
                continue
            mkt_cap = screener_data.get(sym, {}).get("marketCap", 0)
            atr = atr_data.get(sym, {})
            if not atr:
                continue
            mkt_cap_M = mkt_cap / 1e6
            dollar_vol_M = atr.get("avg_dollar_vol_30d", 0) / 1e6
            atr_pct = atr.get("atr_pct_180d", 0)

            if mkt_cap_M < filters["min_cap_M"]:
                continue
            if mkt_cap_M > filters["max_cap_B"] * 1000:
                continue
            if dollar_vol_M < filters["min_vol_M"]:
                continue
            if atr_pct < filters["atr_min"]:
                continue
            if atr_pct > filters["atr_max"]:
                continue
            candidates.append((sym, {
                "symbol": sym,
                "name": info.get("name", ""),
                "factset_sector": sector_name,
                "industry_key": info.get("industry_key", ""),
                "market_cap": mkt_cap,
                "avg_dollar_vol_30d": atr.get("avg_dollar_vol_30d", 0),
                "atr_pct_180d": atr.get("atr_pct_180d", 0),
                "atr_pct_30d": atr.get("atr_pct_30d", 0),
                "last_close": atr.get("last_close", 0),
            }))
        candidates.sort(key=lambda x: x[1]["avg_dollar_vol_30d"], reverse=True)
        target = SECTOR_FILTERS[sector_name]["n"]
        selected = candidates[:target]
        for sym, data in selected:
            universe[sym] = data
        stats[sector_name] = {"target": target, "candidates": len(candidates), "selected": len(selected)}
    return universe, stats


def main():
    log("=== Expanding Universe to 2,000 companies ===\n")

    # Load cached data
    ticker_map, screener_data, atr_data = load_caches()
    log(f"Loaded: {len(ticker_map)} classified, {len(screener_data)} screener, {len(atr_data)} ATR\n")

    # Step 1: Try with relaxed filters on existing data
    log("Step 1: Apply relaxed filters on existing data...")
    universe, stats = apply_filters(ticker_map, screener_data, atr_data, RELAXED_FILTERS)
    total = sum(s["selected"] for s in stats.values())
    log(f"  Relaxed filters on existing data: {total} companies\n")

    # Identify deficit sectors
    deficit_sectors = {}
    for sector, s in stats.items():
        target = SECTOR_FILTERS[sector]["n"]
        if s["selected"] < target:
            deficit_sectors[sector] = target - s["selected"]
    log(f"Deficit sectors: {len(deficit_sectors)} sectors, need {sum(deficit_sectors.values())} more\n")

    if not deficit_sectors:
        log("All sectors filled! No expansion needed.")
    else:
        # Step 2: Search for more tickers in deficit sectors
        log("Step 2: Searching for additional tickers in deficit sectors...")
        all_existing = set(screener_data.keys())
        new_screener = {}
        new_to_resolve = []

        for factset_sector, needed in sorted(deficit_sectors.items(), key=lambda x: -x[1]):
            yahoo_sectors = FACTSET_TO_YAHOO_SECTORS.get(factset_sector, [])
            relaxed = RELAXED_FILTERS[factset_sector]
            for ys in yahoo_sectors:
                log(f"  Searching {ys} for {factset_sector} (need {needed} more)...")
                found = search_sector_tickers(
                    ys,
                    min_cap=relaxed["min_cap_M"] * 1e6,
                    max_cap=relaxed["max_cap_B"] * 1e9,
                    existing_syms=all_existing,
                )
                log(f"    Found {len(found)} new tickers")
                for sym, data in found.items():
                    new_screener[sym] = data
                    if sym not in ticker_map:
                        new_to_resolve.append(sym)
                all_existing.update(found.keys())
                time.sleep(0.5)

        # Add new screener data
        screener_data.update(new_screener)
        log(f"\nTotal new tickers from screener: {len(new_screener)}")

        # Step 3: Resolve industries for new tickers
        if new_to_resolve:
            log(f"\nStep 3: Resolving industries for {len(new_to_resolve)} new tickers...")
            batch_size = 100
            for i in range(0, len(new_to_resolve), batch_size):
                batch = new_to_resolve[i:i+batch_size]
                resolved = resolve_industry_batch(batch)
                ticker_map.update(resolved)
                done = min(i + batch_size, len(new_to_resolve))
                log(f"  Resolved {done}/{len(new_to_resolve)} ({len(resolved)} mapped)")

        # Step 4: Compute ATR for new tickers
        new_need_atr = [s for s in new_screener if s in ticker_map and s not in atr_data]
        if new_need_atr:
            log(f"\nStep 4: Computing ATR for {len(new_need_atr)} new tickers...")
            new_atr = compute_atr_batch(new_need_atr, atr_data)
            atr_data.update(new_atr)

        # Step 5: Re-apply relaxed filters with expanded data
        log("\nStep 5: Re-applying filters with expanded data...")
        universe, stats = apply_filters(ticker_map, screener_data, atr_data, RELAXED_FILTERS)

    # Save final results
    total = sum(s["selected"] for s in stats.values())

    output_file = Path("insider_universe.json")
    output = {
        "total": total,
        "sector_summary": stats,
        "tickers": universe,
    }
    output_file.write_text(json.dumps(output, indent=2))

    ticker_list_file = Path("insider_universe_tickers.json")
    by_sector = {}
    for sym, data in universe.items():
        sector = data["factset_sector"]
        if sector not in by_sector:
            by_sector[sector] = []
        by_sector[sector].append(sym)
    for sector in by_sector:
        by_sector[sector].sort()
    ticker_list_file.write_text(json.dumps(by_sector, indent=2))

    # Update caches
    (CACHE_DIR / "screener_tickers.json").write_text(json.dumps(screener_data, indent=2))
    (CACHE_DIR / "atr_data.json").write_text(json.dumps(atr_data, indent=2))
    (CACHE_DIR / "industry_tickers.json").write_text(json.dumps({
        k: v for k, v in ticker_map.items()
        if isinstance(v, dict) and "factset_sector" in v
    }, indent=2))

    log(f"\n=== DONE ===")
    log(f"Total universe: {total} companies")
    log(f"Saved to: {output_file} and {ticker_list_file}")

    print(f"\n{'Sector':<25} {'Target':>7} {'Found':>7} {'Selected':>9}")
    print("-" * 52)
    total_target = total_selected = 0
    for sector, s in sorted(stats.items(), key=lambda x: -SECTOR_FILTERS[x[0]]["n"]):
        target = SECTOR_FILTERS[sector]["n"]
        marker = " ✓" if s["selected"] >= target else f" (need {target - s['selected']})"
        print(f"{sector:<25} {target:>7} {s['candidates']:>7} {s['selected']:>9}{marker}")
        total_target += target
        total_selected += s["selected"]
    print("-" * 52)
    print(f"{'TOTAL':<25} {total_target:>7} {'':>7} {total_selected:>9}")


if __name__ == "__main__":
    main()
