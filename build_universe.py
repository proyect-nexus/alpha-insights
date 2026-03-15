"""
Build the 2,000-company insider trading universe.
Filters per sector from insider_universe_filtros_completos.html:
  - Market cap range
  - Min daily volume ($M)
  - ATR% 180d baseline range
  - Target N per FactSet sector
"""

import json
import time
import sys
import os
import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path

# ── FactSet sector definitions ──────────────────────────────────────────────
# Each entry: target_n, min_vol_daily_M, min_mktcap_M, max_mktcap_B, atr_min%, atr_max%
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

# ── Yahoo industry → FactSet sector mapping ─────────────────────────────────
INDUSTRY_TO_SECTOR = {
    # Health Technology (biotech, pharma, devices)
    "biotechnology": "Health Technology",
    "drug-manufacturers-general": "Health Technology",
    "drug-manufacturers-specialty-generic": "Health Technology",
    "medical-devices": "Health Technology",
    "diagnostics-research": "Health Technology",
    "medical-instruments-supplies": "Health Technology",
    "health-information-services": "Health Technology",
    # Health Services
    "healthcare-plans": "Health Services",
    "medical-care-facilities": "Health Services",
    "medical-distribution": "Health Services",
    "pharmaceutical-retailers": "Health Services",
    # Technology Services (software, IT)
    "software-infrastructure": "Technology Services",
    "software-application": "Technology Services",
    "information-technology-services": "Technology Services",
    # Electronic Technology (hardware, semis)
    "semiconductors": "Electronic Technology",
    "semiconductor-equipment-materials": "Electronic Technology",
    "consumer-electronics": "Electronic Technology",
    "computer-hardware": "Electronic Technology",
    "communication-equipment": "Electronic Technology",
    "electronic-components": "Electronic Technology",
    "scientific-technical-instruments": "Electronic Technology",
    "solar": "Electronic Technology",
    "electronics-computer-distribution": "Electronic Technology",
    # Finance
    "banks-diversified": "Finance",
    "credit-services": "Finance",
    "asset-management": "Finance",
    "insurance-diversified": "Finance",
    "capital-markets": "Finance",
    "banks-regional": "Finance",
    "financial-data-stock-exchanges": "Finance",
    "insurance-property-casualty": "Finance",
    "insurance-brokers": "Finance",
    "insurance-life": "Finance",
    "insurance-specialty": "Finance",
    "mortgage-finance": "Finance",
    "insurance-reinsurance": "Finance",
    "financial-conglomerates": "Finance",
    "shell-companies": "Finance",
    # Energy Minerals
    "oil-gas-integrated": "Energy Minerals",
    "oil-gas-midstream": "Energy Minerals",
    "oil-gas-e-p": "Energy Minerals",
    "oil-gas-equipment-services": "Energy Minerals",
    "oil-gas-refining-marketing": "Energy Minerals",
    "uranium": "Energy Minerals",
    "oil-gas-drilling": "Energy Minerals",
    "thermal-coal": "Energy Minerals",
    # Consumer Non-Durables
    "discount-stores": "Consumer Non-Durables",
    "beverages-non-alcoholic": "Consumer Non-Durables",
    "household-personal-products": "Consumer Non-Durables",
    "tobacco": "Consumer Non-Durables",
    "packaged-foods": "Consumer Non-Durables",
    "confectioners": "Consumer Non-Durables",
    "farm-products": "Consumer Non-Durables",
    "food-distribution": "Consumer Non-Durables",
    "grocery-stores": "Consumer Non-Durables",
    "beverages-brewers": "Consumer Non-Durables",
    "education-training-services": "Consumer Non-Durables",
    "beverages-wineries-distilleries": "Consumer Non-Durables",
    # Retail Trade
    "internet-retail": "Retail Trade",
    "home-improvement-retail": "Retail Trade",
    "apparel-retail": "Retail Trade",
    "specialty-retail": "Retail Trade",
    "auto-truck-dealerships": "Retail Trade",
    "department-stores": "Retail Trade",
    # Consumer Durables
    "auto-manufacturers": "Consumer Durables",
    "auto-parts": "Consumer Durables",
    "residential-construction": "Consumer Durables",
    "packaging-containers": "Consumer Durables",
    "furnishings-fixtures-appliances": "Consumer Durables",
    "recreational-vehicles": "Consumer Durables",
    "footwear-accessories": "Consumer Durables",
    "luxury-goods": "Consumer Durables",
    "textile-manufacturing": "Consumer Durables",
    "apparel-manufacturing": "Consumer Durables",
    # Consumer Services
    "restaurants": "Consumer Services",
    "travel-services": "Consumer Services",
    "lodging": "Consumer Services",
    "resorts-casinos": "Consumer Services",
    "leisure": "Consumer Services",
    "gambling": "Consumer Services",
    "personal-services": "Consumer Services",
    # Producer Manufacturing
    "aerospace-defense": "Producer Manufacturing",
    "specialty-industrial-machinery": "Producer Manufacturing",
    "farm-heavy-construction-machinery": "Producer Manufacturing",
    "building-products-equipment": "Producer Manufacturing",
    "electrical-equipment-parts": "Producer Manufacturing",
    "tools-accessories": "Producer Manufacturing",
    "metal-fabrication": "Producer Manufacturing",
    "conglomerates": "Producer Manufacturing",
    # Industrial Services
    "engineering-construction": "Industrial Services",
    "pollution-treatment-controls": "Industrial Services",
    "infrastructure-operations": "Industrial Services",
    # Transportation
    "railroads": "Transportation",
    "integrated-freight-logistics": "Transportation",
    "airlines": "Transportation",
    "trucking": "Transportation",
    "marine-shipping": "Transportation",
    "airports-air-services": "Transportation",
    # Commercial Services
    "specialty-business-services": "Commercial Services",
    "waste-management": "Commercial Services",
    "rental-leasing-services": "Commercial Services",
    "consulting-services": "Commercial Services",
    "security-protection-services": "Commercial Services",
    "staffing-employment-services": "Commercial Services",
    "business-equipment-supplies": "Commercial Services",
    # Distribution Services
    "industrial-distribution": "Distribution Services",
    # Non-Energy Minerals
    "gold": "Non-Energy Minerals",
    "copper": "Non-Energy Minerals",
    "steel": "Non-Energy Minerals",
    "other-industrial-metals-mining": "Non-Energy Minerals",
    "other-precious-metals-mining": "Non-Energy Minerals",
    "aluminum": "Non-Energy Minerals",
    "silver": "Non-Energy Minerals",
    "building-materials": "Non-Energy Minerals",
    "coking-coal": "Non-Energy Minerals",
    # Process Industries
    "specialty-chemicals": "Process Industries",
    "agricultural-inputs": "Process Industries",
    "chemicals": "Process Industries",
    "lumber-wood-production": "Process Industries",
    "paper-paper-products": "Process Industries",
    # Utilities
    "utilities-regulated-electric": "Utilities",
    "utilities-independent-power-producers": "Utilities",
    "utilities-regulated-gas": "Utilities",
    "utilities-diversified": "Utilities",
    "utilities-renewable": "Utilities",
    "utilities-regulated-water": "Utilities",
    # Communications
    "internet-content-information": "Communications",
    "telecom-services": "Communications",
    "entertainment": "Communications",
    "advertising-agencies": "Communications",
    "electronic-gaming-multimedia": "Communications",
    "publishing": "Communications",
    "broadcasting": "Communications",
    # Miscellaneous (Real Estate + anything else)
    "reit-specialty": "Miscellaneous",
    "reit-industrial": "Miscellaneous",
    "reit-healthcare-facilities": "Miscellaneous",
    "reit-retail": "Miscellaneous",
    "reit-residential": "Miscellaneous",
    "real-estate-services": "Miscellaneous",
    "reit-mortgage": "Miscellaneous",
    "reit-diversified": "Miscellaneous",
    "reit-office": "Miscellaneous",
    "reit-hotel-motel": "Miscellaneous",
    "real-estate-development": "Miscellaneous",
    "real-estate-diversified": "Miscellaneous",
}

# Yahoo sector → fallback FactSet sector (when industry not available)
YAHOO_SECTOR_FALLBACK = {
    "Healthcare": "Health Technology",
    "Technology": "Technology Services",
    "Financial Services": "Finance",
    "Energy": "Energy Minerals",
    "Consumer Defensive": "Consumer Non-Durables",
    "Consumer Cyclical": "Consumer Durables",
    "Industrials": "Producer Manufacturing",
    "Basic Materials": "Non-Energy Minerals",
    "Utilities": "Utilities",
    "Communication Services": "Communications",
    "Real Estate": "Miscellaneous",
}

CACHE_DIR = Path("universe_cache")
CACHE_DIR.mkdir(exist_ok=True)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Step 1: Collect tickers from Yahoo Industries ───────────────────────────
def collect_industry_tickers():
    cache_file = CACHE_DIR / "industry_tickers.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        log(f"Loaded {len(data)} tickers from industry cache")
        return data

    log("Collecting tickers from all Yahoo industries...")
    ticker_map = {}  # symbol → {industry_key, factset_sector, name}

    yahoo_sectors = [
        "technology", "healthcare", "financial-services", "energy",
        "consumer-defensive", "consumer-cyclical", "industrials",
        "basic-materials", "utilities", "communication-services", "real-estate"
    ]

    for sector_key in yahoo_sectors:
        log(f"  Sector: {sector_key}")
        try:
            sector = yf.Sector(sector_key)
            industries = sector.industries
        except Exception as e:
            log(f"    Error getting industries: {e}")
            continue

        for ind_key in industries.index:
            factset = INDUSTRY_TO_SECTOR.get(ind_key)
            if not factset:
                log(f"    Warning: unmapped industry {ind_key}")
                continue

            try:
                industry = yf.Industry(ind_key)
                companies = industry.top_companies
                if companies is not None and len(companies) > 0:
                    for sym in companies.index:
                        name = companies.loc[sym, "name"] if "name" in companies.columns else ""
                        ticker_map[sym] = {
                            "industry_key": ind_key,
                            "factset_sector": factset,
                            "name": str(name),
                        }
                    log(f"    {ind_key}: {len(companies)} companies")
                else:
                    log(f"    {ind_key}: no companies returned")
            except Exception as e:
                log(f"    {ind_key}: error {e}")
            time.sleep(0.2)

    cache_file.write_text(json.dumps(ticker_map, indent=2))
    log(f"Collected {len(ticker_map)} unique tickers from industries")
    return ticker_map


# ── Step 2: Get additional tickers via screener (paginated) ─────────────────
def collect_screener_tickers(existing_tickers):
    cache_file = CACHE_DIR / "screener_tickers.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        log(f"Loaded {len(data)} tickers from screener cache")
        return data

    log("Collecting additional tickers via screener...")
    screener_data = {}  # symbol → {marketCap, avgVol, price}
    offset = 0
    size = 250

    while True:
        try:
            q = yf.EquityQuery('and', [
                yf.EquityQuery('eq', ['region', 'us']),
                yf.EquityQuery('gt', ['intradaymarketcap', 5e7]),
                yf.EquityQuery('gt', ['avgdailyvol3m', 50000]),
            ])
            result = yf.screen(q, size=size, offset=offset)
            quotes = result.get('quotes', [])
            if not quotes:
                break

            for q in quotes:
                sym = q.get('symbol', '')
                if not sym:
                    continue
                screener_data[sym] = {
                    "marketCap": q.get("marketCap", 0),
                    "avgVolume": q.get("averageDailyVolume3Month", 0),
                    "price": q.get("regularMarketPrice", 0),
                    "name": q.get("longName") or q.get("shortName", ""),
                }

            total = result.get('total', 0)
            offset += size
            log(f"  Screener: {offset}/{total} fetched ({len(screener_data)} unique)")

            if offset >= total:
                break
            time.sleep(0.3)
        except Exception as e:
            log(f"  Screener error at offset {offset}: {e}")
            break

    cache_file.write_text(json.dumps(screener_data, indent=2))
    log(f"Screener collected {len(screener_data)} tickers total")
    return screener_data


# ── Step 3: Resolve missing industry classifications ────────────────────────
def resolve_industries(ticker_map, screener_data):
    """For screener tickers not in ticker_map, try to get their industry."""
    cache_file = CACHE_DIR / "resolved_industries.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        log(f"Loaded {len(data)} resolved industries from cache")
        return data

    missing = [sym for sym in screener_data if sym not in ticker_map]
    log(f"Resolving industry for {len(missing)} tickers not in industry map...")

    resolved = {}
    batch_size = 50
    for i in range(0, len(missing), batch_size):
        batch = missing[i:i+batch_size]
        for sym in batch:
            try:
                info = yf.Ticker(sym).info
                industry_key = info.get("industryKey", "")
                sector = info.get("sector", "")
                factset = INDUSTRY_TO_SECTOR.get(industry_key)
                if not factset and sector:
                    factset = YAHOO_SECTOR_FALLBACK.get(sector)
                if factset:
                    resolved[sym] = {
                        "industry_key": industry_key,
                        "factset_sector": factset,
                        "name": info.get("longName") or info.get("shortName", ""),
                    }
            except Exception:
                pass
            time.sleep(0.15)

        done = min(i + batch_size, len(missing))
        log(f"  Resolved {done}/{len(missing)} ({len(resolved)} mapped)")

    cache_file.write_text(json.dumps(resolved, indent=2))
    log(f"Resolved {len(resolved)} additional tickers")
    return resolved


# ── Step 4: Download price data and compute ATR% ───────────────────────────
def compute_atr_pct(symbols, period="1y"):
    """Compute ATR% over 180 trading days for a list of symbols."""
    cache_file = CACHE_DIR / "atr_data.json"
    if cache_file.exists():
        data = json.loads(cache_file.read_text())
        log(f"Loaded ATR data for {len(data)} tickers from cache")
        return data

    log(f"Downloading price data for {len(symbols)} tickers...")
    atr_results = {}

    # Download in batches to avoid overwhelming yfinance
    batch_size = 100
    all_symbols = list(symbols)

    for i in range(0, len(all_symbols), batch_size):
        batch = all_symbols[i:i+batch_size]
        batch_str = " ".join(batch)
        try:
            data = yf.download(batch_str, period=period, progress=False, threads=True)
            if data.empty:
                continue

            for sym in batch:
                try:
                    if len(batch) == 1:
                        high = data["High"]
                        low = data["Low"]
                        close = data["Close"]
                    else:
                        high = data["High"][sym]
                        low = data["Low"][sym]
                        close = data["Close"][sym]

                    high = high.dropna()
                    low = low.dropna()
                    close = close.dropna()

                    if len(close) < 60:
                        continue

                    tr = pd.concat([
                        high - low,
                        (high - close.shift(1)).abs(),
                        (low - close.shift(1)).abs()
                    ], axis=1).max(axis=1)

                    # ATR% 180d baseline (or max available)
                    lookback = min(180, len(tr))
                    atr_180 = tr.tail(lookback).mean()
                    avg_close_180 = close.tail(lookback).mean()
                    atr_pct_180 = (atr_180 / avg_close_180 * 100) if avg_close_180 > 0 else 0

                    # ATR% 30d signal
                    atr_30 = tr.tail(30).mean()
                    avg_close_30 = close.tail(30).mean()
                    atr_pct_30 = (atr_30 / avg_close_30 * 100) if avg_close_30 > 0 else 0

                    # Daily volume in $ (avg 30d)
                    vol = data["Volume"][sym] if len(batch) > 1 else data["Volume"]
                    avg_dollar_vol = (vol.tail(30) * close.tail(30)).mean()

                    atr_results[sym] = {
                        "atr_pct_180d": round(atr_pct_180, 3),
                        "atr_pct_30d": round(atr_pct_30, 3),
                        "avg_dollar_vol_30d": round(float(avg_dollar_vol), 0),
                        "last_close": round(float(close.iloc[-1]), 2),
                    }
                except Exception:
                    pass
        except Exception as e:
            log(f"  Download error batch {i}: {e}")

        done = min(i + batch_size, len(all_symbols))
        log(f"  Price data: {done}/{len(all_symbols)} processed ({len(atr_results)} valid)")
        time.sleep(0.5)

    cache_file.write_text(json.dumps(atr_results, indent=2))
    log(f"Computed ATR for {len(atr_results)} tickers")
    return atr_results


# ── Step 5: Apply filters and select universe ──────────────────────────────
def build_final_universe(ticker_map, screener_data, atr_data):
    """Apply per-sector filters and select top N per sector."""

    # Build combined dataset
    all_tickers = {}
    for sym, info in ticker_map.items():
        mkt_cap = screener_data.get(sym, {}).get("marketCap", 0)
        atr = atr_data.get(sym, {})
        if not atr:
            continue
        all_tickers[sym] = {
            "symbol": sym,
            "name": info.get("name", ""),
            "factset_sector": info["factset_sector"],
            "industry_key": info.get("industry_key", ""),
            "market_cap": mkt_cap,
            "avg_dollar_vol_30d": atr.get("avg_dollar_vol_30d", 0),
            "atr_pct_180d": atr.get("atr_pct_180d", 0),
            "atr_pct_30d": atr.get("atr_pct_30d", 0),
            "last_close": atr.get("last_close", 0),
        }

    log(f"Combined dataset: {len(all_tickers)} tickers with full data")

    # Apply per-sector filters
    universe = {}
    sector_stats = {}

    for sector_name, filters in SECTOR_FILTERS.items():
        candidates = []
        for sym, data in all_tickers.items():
            if data["factset_sector"] != sector_name:
                continue

            mkt_cap_M = data["market_cap"] / 1e6
            dollar_vol_M = data["avg_dollar_vol_30d"] / 1e6
            atr_pct = data["atr_pct_180d"]

            # Apply filters
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

            candidates.append(data)

        # Sort by dollar volume descending (most liquid first) as selection criteria
        candidates.sort(key=lambda x: x["avg_dollar_vol_30d"], reverse=True)
        selected = candidates[:filters["n"]]

        for c in selected:
            universe[c["symbol"]] = c

        sector_stats[sector_name] = {
            "target": filters["n"],
            "candidates": len(candidates),
            "selected": len(selected),
        }
        log(f"  {sector_name}: {len(candidates)} candidates → {len(selected)}/{filters['n']} selected")

    return universe, sector_stats


def main():
    log("=== Building Insider Trading Universe (2,000 companies) ===\n")

    # Step 1: Collect tickers from Yahoo industries
    ticker_map = collect_industry_tickers()
    log(f"\nStep 1 done: {len(ticker_map)} tickers from industries\n")

    # Step 2: Get additional tickers via screener
    screener_data = collect_screener_tickers(ticker_map)
    log(f"\nStep 2 done: {len(screener_data)} tickers from screener\n")

    # Step 3: Resolve missing industry classifications
    resolved = resolve_industries(ticker_map, screener_data)
    ticker_map.update(resolved)
    log(f"\nStep 3 done: {len(ticker_map)} total classified tickers\n")

    # Step 4: Compute ATR% for all classified tickers that are also in screener
    all_symbols = set(ticker_map.keys()) & set(screener_data.keys())
    log(f"Tickers with both classification and screener data: {len(all_symbols)}")
    atr_data = compute_atr_pct(all_symbols)
    log(f"\nStep 4 done: ATR data for {len(atr_data)} tickers\n")

    # Step 5: Apply filters and build final universe
    universe, sector_stats = build_final_universe(ticker_map, screener_data, atr_data)

    # Save results
    output_file = Path("insider_universe.json")
    output = {
        "total": len(universe),
        "sector_summary": sector_stats,
        "tickers": universe,
    }
    output_file.write_text(json.dumps(output, indent=2))

    # Also save a simple ticker list per sector (for tickers.py integration)
    ticker_list_file = Path("insider_universe_tickers.json")
    by_sector = {}
    for sym, data in universe.items():
        sector = data["factset_sector"]
        if sector not in by_sector:
            by_sector[sector] = []
        by_sector[sector].append(sym)
    # Sort each sector list
    for sector in by_sector:
        by_sector[sector].sort()
    ticker_list_file.write_text(json.dumps(by_sector, indent=2))

    log(f"\n=== DONE ===")
    log(f"Total universe: {len(universe)} companies")
    log(f"Saved to: {output_file} and {ticker_list_file}")

    print(f"\n{'Sector':<25} {'Target':>7} {'Found':>7} {'Selected':>9}")
    print("-" * 52)
    total_target = total_selected = 0
    for sector, stats in sorted(sector_stats.items(), key=lambda x: -x[1]['target']):
        print(f"{sector:<25} {stats['target']:>7} {stats['candidates']:>7} {stats['selected']:>9}")
        total_target += stats['target']
        total_selected += stats['selected']
    print("-" * 52)
    print(f"{'TOTAL':<25} {total_target:>7} {'':>7} {total_selected:>9}")


if __name__ == "__main__":
    main()
