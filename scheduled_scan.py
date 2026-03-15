"""
Scheduled scan script for GitHub Actions.
Runs a full scan across all indices, saves results to scans/scheduled/.
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import config
from scanner import scan_ticker
from tickers import INDICES, get_index_tickers


SCHEDULED_DIR = Path(__file__).parent / "scans" / "scheduled"
INDEX_FILE = SCHEDULED_DIR / "index.json"


def collect_all_tickers() -> list[str]:
    """Collect all unique tickers from all indices."""
    seen = set()
    result = []
    for key in INDICES:
        tickers = get_index_tickers(key)
        for t in tickers:
            if t not in seen:
                seen.add(t)
                result.append(t)
    return result


def run_scan(threshold: int) -> dict:
    """Run full scan and return results dict."""
    tickers = collect_all_tickers()
    total = len(tickers)
    print(f"Scanning {total} tickers (threshold={threshold})...")

    all_alerts = []
    errors = []
    scanned = 0

    for i, ticker in enumerate(tickers):
        progress = f"[{i + 1}/{total}]"
        try:
            entries = scan_ticker(ticker)
            alerts = [e for e in entries if e["score"] >= threshold]
            if alerts:
                all_alerts.extend(alerts)
                print(f"  {progress} {ticker}: {len(alerts)} alert(s) (max score {max(a['score'] for a in alerts)})")
            else:
                print(f"  {progress} {ticker}: clean")
            scanned += 1
        except Exception as ex:
            errors.append({"ticker": ticker, "error": str(ex)})
            print(f"  {progress} {ticker}: ERROR - {ex}")

        # Rate limiting
        if (i + 1) % config.BATCH_SIZE == 0:
            time.sleep(config.DELAY_BETWEEN_BATCHES)
        else:
            time.sleep(config.DELAY_BETWEEN_TICKERS)

    # Group alerts by ticker
    by_ticker: dict[str, list[dict]] = {}
    for a in all_alerts:
        by_ticker.setdefault(a["ticker"], []).append(a)

    insights = []
    for ticker, alerts in sorted(by_ticker.items(), key=lambda x: max(a["score"] for a in x[1]), reverse=True):
        alerts_sorted = sorted(alerts, key=lambda a: a["score"], reverse=True)
        insights.append({
            "ticker": ticker,
            "company": alerts_sorted[0].get("company", ticker),
            "spot": alerts_sorted[0].get("spot"),
            "max_score": max(a["score"] for a in alerts_sorted),
            "total_notional": sum(a.get("notional", 0) for a in alerts_sorted),
            "alert_count": len(alerts_sorted),
            "alerts": alerts_sorted,
        })

    # Classify severity
    high = sum(1 for a in all_alerts if a["score"] >= 70)
    medium = sum(1 for a in all_alerts if a["score"] < 70)

    scan_time = datetime.now()
    result = {
        "scan_time": scan_time.isoformat(),
        "tickers_scanned": scanned,
        "tickers_with_alerts": len(by_ticker),
        "total_alerts": len(all_alerts),
        "threshold": threshold,
        "summary": {
            "total": len(all_alerts),
            "high": high,
            "medium": medium,
        },
        "insights": insights,
    }

    if errors:
        result["errors"] = errors

    return result


def save_result(result: dict) -> Path:
    """Save scan result to JSON and update index."""
    SCHEDULED_DIR.mkdir(parents=True, exist_ok=True)

    scan_time = datetime.fromisoformat(result["scan_time"])
    filename = scan_time.strftime("%Y-%m-%d_%H-%M") + ".json"
    filepath = SCHEDULED_DIR / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)

    # Update index.json
    index = []
    if INDEX_FILE.exists():
        try:
            with open(INDEX_FILE, "r", encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, ValueError):
            index = []

    index.append({
        "filename": filename,
        "date": scan_time.strftime("%Y-%m-%d"),
        "time": scan_time.strftime("%H:%M"),
        "total_alerts": result["total_alerts"],
        "tickers_scanned": result["tickers_scanned"],
        "tickers_with_alerts": result["tickers_with_alerts"],
    })

    # Sort by date/time descending
    index.sort(key=lambda x: x["filename"], reverse=True)

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return filepath


def print_summary(result: dict) -> None:
    """Print summary to stdout for GitHub Actions logs."""
    print("\n" + "=" * 60)
    print("SCHEDULED SCAN COMPLETE")
    print("=" * 60)
    print(f"  Time:              {result['scan_time']}")
    print(f"  Tickers scanned:   {result['tickers_scanned']}")
    print(f"  Tickers w/ alerts: {result['tickers_with_alerts']}")
    print(f"  Total alerts:      {result['total_alerts']}")
    print(f"  High (>=70):       {result['summary']['high']}")
    print(f"  Medium (<70):      {result['summary']['medium']}")
    print(f"  Threshold:         {result['threshold']}")

    if result.get("errors"):
        print(f"  Errors:            {len(result['errors'])}")

    if result["insights"]:
        print("\nTop insights:")
        for ins in result["insights"][:10]:
            print(f"  {ins['ticker']:6s} | score {ins['max_score']:5.1f} | "
                  f"{ins['alert_count']} alerts | "
                  f"${ins['total_notional']:,.0f} notional | "
                  f"{ins['company']}")

    print("=" * 60)


def build_email_body(result: dict) -> str | None:
    """Build email alert body for high-score tickers (>=50). Returns None if no alerts."""
    critical = [ins for ins in result["insights"] if ins["max_score"] >= 50]
    if not critical:
        return None

    lines = []
    lines.append(f"Scan: {result['scan_time']}")
    lines.append(f"Tickers escaneados: {result['tickers_scanned']}")
    lines.append(f"Total alertas: {result['total_alerts']}")
    lines.append("")
    lines.append(f"{'='*60}")
    lines.append(f"ALERTAS (score >= 50)")
    lines.append(f"{'='*60}")

    for ins in critical:
        lines.append("")
        lines.append(f"  {ins['ticker']} — {ins['company']}")
        lines.append(f"  Precio: ${ins['spot']}")
        lines.append(f"  Score: {ins['max_score']}")
        lines.append(f"  Notional total: ${ins['total_notional']:,.0f}")
        lines.append(f"  Contratos inusuales: {ins['alert_count']}")

        for a in ins["alerts"][:3]:
            lines.append(f"    - Strike ${a['strike']} exp {a['expiration']} "
                         f"| score {a['score']} | vol {a['volume']:,} "
                         f"| V/OI {a['vol_oi_ratio']}x | {a['reason'][:80]}")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scheduled insider trading scan")
    parser.add_argument("--threshold", type=int, default=40,
                        help="Minimum score threshold (default: 40)")
    args = parser.parse_args()

    result = run_scan(args.threshold)
    filepath = save_result(result)
    print_summary(result)
    print(f"\nResults saved to: {filepath}")

    # Write email alert file if critical alerts exist
    email_body = build_email_body(result)
    if email_body:
        alert_path = SCHEDULED_DIR / "latest_alert.txt"
        with open(alert_path, "w", encoding="utf-8") as f:
            f.write(email_body)
        print(f"\nCRITICAL ALERTS FOUND — email body saved to {alert_path}")
        # Set GitHub Actions output
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write("has_critical=true\n")
    else:
        print("\nNo critical alerts (score >= 50)")
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write("has_critical=false\n")
