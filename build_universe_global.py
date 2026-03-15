"""
Build the 2,000-company insider trading universe — global edition.
Priority: fill with US first (original strict filters), then fill gaps
from international markets using the same sector filters.
"""

import json
import time
import yfinance as yf
import pandas as pd
import numpy as np
from pathlib import Path

CACHE_DIR = Path("universe_cache")
CACHE_DIR.mkdir(exist_ok=True)

# ── Original strict filters from the HTML table ────────────────────────────
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

# Yahoo industry → FactSet sector
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

# FactSet → Yahoo screener sector names
FACTSET_TO_YAHOO_SECTORS = {
    "Health Technology": ["Healthcare"], "Health Services": ["Healthcare"],
    "Technology Services": ["Technology"], "Electronic Technology": ["Technology"],
    "Finance": ["Financial Services"],
    "Energy Minerals": ["Energy"],
    "Consumer Non-Durables": ["Consumer Defensive"],
    "Retail Trade": ["Consumer Cyclical"], "Consumer Durables": ["Consumer Cyclical"],
    "Consumer Services": ["Consumer Cyclical"],
    "Producer Manufacturing": ["Industrials"], "Industrial Services": ["Industrials"],
    "Transportation": ["Industrials"], "Commercial Services": ["Industrials"],
    "Distribution Services": ["Industrials"],
    "Non-Energy Minerals": ["Basic Materials"], "Process Industries": ["Basic Materials"],
    "Utilities": ["Utilities"], "Communications": ["Communication Services"],
    "Miscellaneous": ["Real Estate"],
}

# Regions ordered by priority (US first, then liquid markets)
ALL_REGIONS = [
    "us", "ca", "gb", "de", "fr", "nl", "ch", "se", "no", "dk", "fi",  # Americas + Europe
    "ie", "be", "at", "es", "it", "pt",                                   # More Europe
    "jp", "hk", "kr", "tw", "sg", "au", "nz",                            # Asia-Pacific
    "in", "br", "mx", "za", "il",                                         # Emerging
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── Screener: paginated fetch for a region ──────────────────────────────────
def screener_fetch_region(region, min_cap=5e7, extra_filters=None):
    """Fetch all tickers from screener for a region. Returns {sym: {marketCap, avgVolume, price, name}}."""
    tickers = {}
    offset = 0
    size = 250
    retries = 0

    filters = [
        yf.EquityQuery('eq', ['region', region]),
        yf.EquityQuery('gt', ['intradaymarketcap', min_cap]),
        yf.EquityQuery('gt', ['avgdailyvol3m', 30000]),
    ]
    if extra_filters:
        filters.extend(extra_filters)

    q = yf.EquityQuery('and', filters)

    while True:
        try:
            result = yf.screen(q, size=size, offset=offset)
            quotes = result.get('quotes', [])
            if not quotes:
                break
            for qt in quotes:
                sym = qt.get('symbol', '')
                if sym:
                    tickers[sym] = {
                        "marketCap": qt.get("marketCap", 0),
                        "avgVolume": qt.get("averageDailyVolume3Month", 0),
                        "price": qt.get("regularMarketPrice", 0),
                        "name": qt.get("longName") or qt.get("shortName", ""),
                        "region": region,
                    }
            total = result.get('total', 0)
            offset += size
            if offset >= total:
                break
            retries = 0
            time.sleep(0.3)
        except Exception as e:
            err = str(e)
            if "Rate" in err or "429" in err:
                retries += 1
                if retries > 3:
                    log(f"    Rate limited on {region}, stopping at {len(tickers)} tickers")
                    break
                time.sleep(5 * retries)
            else:
                log(f"    Error on {region}: {e}")
                break
    return tickers


# ── Resolve industry for a list of symbols ──────────────────────────────────
def resolve_industries(symbols, existing_map):
    """Get factset_sector for symbols not already in existing_map."""
    to_resolve = [s for s in symbols if s not in existing_map]
    if not to_resolve:
        return {}

    results = {}
    for i, sym in enumerate(to_resolve):
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
        if (i + 1) % 100 == 0:
            log(f"    Resolved {i+1}/{len(to_resolve)} ({len(results)} mapped)")
    return results


# ── Compute ATR% for symbols ───────────────────────────────────────────────
def compute_atr(symbols, existing_atr):
    new_syms = [s for s in symbols if s not in existing_atr]
    if not new_syms:
        return {}

    results = {}
    batch_size = 80
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
            log(f"    ATR download error: {e}")
        done = min(i + batch_size, len(new_syms))
        if done % 200 == 0 or done == len(new_syms):
            log(f"    ATR progress: {done}/{len(new_syms)} ({len(results)} valid)")
        time.sleep(0.5)
    return results


# ── Apply sector filters ───────────────────────────────────────────────────
def select_from_pool(pool, filters, already_selected=None):
    """
    pool: list of dicts with symbol, factset_sector, market_cap, avg_dollar_vol_30d, atr_pct_180d, etc.
    Returns selected symbols per sector, respecting already_selected.
    """
    already = already_selected or {}
    universe = dict(already)
    stats = {}

    for sector_name, f in filters.items():
        existing_count = sum(1 for v in already.values() if v["factset_sector"] == sector_name)
        remaining = f["n"] - existing_count

        candidates = []
        for item in pool:
            if item["symbol"] in universe:
                continue
            if item["factset_sector"] != sector_name:
                continue
            mkt_cap_M = item["market_cap"] / 1e6
            dollar_vol_M = item["avg_dollar_vol_30d"] / 1e6
            atr_pct = item["atr_pct_180d"]
            if mkt_cap_M < f["min_cap_M"]:
                continue
            if mkt_cap_M > f["max_cap_B"] * 1000:
                continue
            if dollar_vol_M < f["min_vol_M"]:
                continue
            if atr_pct < f["atr_min"]:
                continue
            if atr_pct > f["atr_max"]:
                continue
            candidates.append(item)

        # Sort by dollar volume (most liquid first)
        candidates.sort(key=lambda x: x["avg_dollar_vol_30d"], reverse=True)
        selected = candidates[:max(0, remaining)]
        for c in selected:
            universe[c["symbol"]] = c

        stats[sector_name] = {
            "target": f["n"],
            "existing": existing_count,
            "new_candidates": len(candidates),
            "new_selected": len(selected),
            "total": existing_count + len(selected),
        }
    return universe, stats


def build_pool(ticker_map, screener_data, atr_data, region_filter=None):
    """Build a list of ticker dicts ready for filtering."""
    pool = []
    for sym, info in ticker_map.items():
        if sym not in atr_data:
            continue
        sc = screener_data.get(sym, {})
        mkt_cap = sc.get("marketCap", 0)
        if mkt_cap == 0:
            continue
        atr = atr_data[sym]
        region = sc.get("region", "us")
        if region_filter and region not in region_filter:
            continue
        pool.append({
            "symbol": sym,
            "name": info.get("name", ""),
            "factset_sector": info["factset_sector"],
            "industry_key": info.get("industry_key", ""),
            "market_cap": mkt_cap,
            "avg_dollar_vol_30d": atr.get("avg_dollar_vol_30d", 0),
            "atr_pct_180d": atr.get("atr_pct_180d", 0),
            "atr_pct_30d": atr.get("atr_pct_30d", 0),
            "last_close": atr.get("last_close", 0),
            "region": region,
        })
    return pool


def main():
    log("=== Building Global Insider Universe (2,000 companies) ===\n")

    # ── Load existing US caches ─────────────────────────────────────────────
    ticker_map = {}
    screener_data = {}
    atr_data = {}

    for fname, target in [
        ("industry_tickers.json", ticker_map),
        ("resolved_industries.json", ticker_map),
        ("screener_tickers.json", screener_data),
        ("atr_data.json", atr_data),
    ]:
        p = CACHE_DIR / fname
        if p.exists():
            d = json.loads(p.read_text())
            target.update(d)

    log(f"Loaded US cache: {len(ticker_map)} classified, {len(screener_data)} screener, {len(atr_data)} ATR")

    # Tag existing screener entries as US
    for sym in screener_data:
        if "region" not in screener_data[sym]:
            screener_data[sym]["region"] = "us"

    # ── Phase 1: Select US tickers with strict filters ──────────────────────
    log("\n--- Phase 1: US selection (strict filters) ---")
    us_pool = build_pool(ticker_map, screener_data, atr_data, region_filter={"us"})
    log(f"US pool: {len(us_pool)} tickers with full data")
    universe, stats = select_from_pool(us_pool, SECTOR_FILTERS)
    us_total = len(universe)
    log(f"US selected: {us_total}")

    # Show deficit
    deficit_sectors = {}
    for sector, s in stats.items():
        if s["total"] < SECTOR_FILTERS[sector]["n"]:
            gap = SECTOR_FILTERS[sector]["n"] - s["total"]
            deficit_sectors[sector] = gap
    total_gap = sum(deficit_sectors.values())
    log(f"Deficit: {len(deficit_sectors)} sectors, {total_gap} tickers needed\n")

    if total_gap == 0:
        log("All sectors filled from US! No international search needed.")
    else:
        # ── Phase 2: Fetch international tickers for deficit sectors ────────
        log("--- Phase 2: International search for deficit sectors ---")
        intl_regions = [r for r in ALL_REGIONS if r != "us"]

        # For each deficit sector, search in international markets
        all_new_screener = {}
        for factset_sector, needed in sorted(deficit_sectors.items(), key=lambda x: -x[1]):
            yahoo_sectors = FACTSET_TO_YAHOO_SECTORS.get(factset_sector, [])
            f = SECTOR_FILTERS[factset_sector]
            log(f"\n  [{factset_sector}] need {needed} more")

            sector_new = {}
            for region in intl_regions:
                if len(sector_new) >= needed * 3:  # fetch 3x what we need (many will be filtered out)
                    break
                for ys in yahoo_sectors:
                    try:
                        found = screener_fetch_region(
                            region,
                            min_cap=f["min_cap_M"] * 1e6 * 0.5,  # slightly relaxed for initial fetch
                            extra_filters=[yf.EquityQuery('eq', ['sector', ys])],
                        )
                        new_only = {s: d for s, d in found.items() if s not in screener_data and s not in all_new_screener}
                        if new_only:
                            sector_new.update(new_only)
                            log(f"    {region}/{ys}: +{len(new_only)} new ({len(sector_new)} total for sector)")
                        time.sleep(0.5)
                    except Exception as e:
                        log(f"    {region}/{ys}: error {e}")

            all_new_screener.update(sector_new)

        log(f"\nTotal new international tickers: {len(all_new_screener)}")
        screener_data.update(all_new_screener)

        # ── Phase 3: Resolve industries for new tickers ─────────────────────
        new_to_resolve = [s for s in all_new_screener if s not in ticker_map]
        if new_to_resolve:
            log(f"\n--- Phase 3: Resolving industries for {len(new_to_resolve)} international tickers ---")
            resolved = resolve_industries(new_to_resolve, ticker_map)
            ticker_map.update(resolved)
            log(f"Resolved: {len(resolved)} mapped")

        # ── Phase 4: Compute ATR for new tickers ───────────────────────────
        new_need_atr = [s for s in all_new_screener if s in ticker_map and s not in atr_data]
        if new_need_atr:
            log(f"\n--- Phase 4: Computing ATR for {len(new_need_atr)} international tickers ---")
            new_atr = compute_atr(new_need_atr, atr_data)
            atr_data.update(new_atr)
            log(f"ATR computed: {len(new_atr)}")

        # ── Phase 5: Fill gaps with international tickers ───────────────────
        log("\n--- Phase 5: Fill gaps with international tickers ---")
        intl_pool = build_pool(ticker_map, screener_data, atr_data)
        # Remove items already in universe
        intl_pool = [p for p in intl_pool if p["symbol"] not in universe]
        universe, stats = select_from_pool(intl_pool, SECTOR_FILTERS, already_selected=universe)

    # ── Save results ────────────────────────────────────────────────────────
    final_total = len(universe)

    output_file = Path("insider_universe.json")
    output = {
        "total": final_total,
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

    # Count by region
    region_counts = {}
    for sym, data in universe.items():
        r = data.get("region", screener_data.get(sym, {}).get("region", "us"))
        region_counts[r] = region_counts.get(r, 0) + 1

    # Update caches
    (CACHE_DIR / "screener_tickers.json").write_text(json.dumps(screener_data, indent=2))
    (CACHE_DIR / "atr_data.json").write_text(json.dumps(atr_data, indent=2))
    merged_map = {k: v for k, v in ticker_map.items() if isinstance(v, dict) and "factset_sector" in v}
    (CACHE_DIR / "industry_tickers.json").write_text(json.dumps(merged_map, indent=2))

    log(f"\n{'='*56}")
    log(f"TOTAL UNIVERSE: {final_total} companies")
    log(f"{'='*56}")

    print(f"\n{'Sector':<25} {'Target':>7} {'US':>5} {'Intl':>5} {'Total':>7}")
    print("-" * 55)
    total_target = total_selected = 0
    for sector, s in sorted(stats.items(), key=lambda x: -SECTOR_FILTERS[x[0]]["n"]):
        target = SECTOR_FILTERS[sector]["n"]
        total_in_sector = s["total"]
        # Count US vs intl in this sector
        us_count = sum(1 for sym, d in universe.items()
                       if d["factset_sector"] == sector
                       and screener_data.get(sym, {}).get("region", "us") == "us")
        intl_count = total_in_sector - us_count
        marker = " ok" if total_in_sector >= target else f" -{target - total_in_sector}"
        print(f"{sector:<25} {target:>7} {us_count:>5} {intl_count:>5} {total_in_sector:>7}{marker}")
        total_target += target
        total_selected += total_in_sector
    print("-" * 55)
    print(f"{'TOTAL':<25} {total_target:>7} {'':>5} {'':>5} {total_selected:>7}")

    print(f"\nBy region:")
    for r, c in sorted(region_counts.items(), key=lambda x: -x[1]):
        print(f"  {r.upper()}: {c}")


if __name__ == "__main__":
    main()
