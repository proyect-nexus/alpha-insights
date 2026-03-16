"""
Scheduled scan script for GitHub Actions.
Runs a full scan across all indices, saves results to scans/scheduled/.
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import config
from scanner import scan_ticker
from tickers import INDICES, get_index_tickers

CONCURRENT_WORKERS = 5


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


def _scan_one(ticker: str, threshold: int) -> dict:
    """Scan a single ticker. Returns dict with results or error."""
    try:
        entries = scan_ticker(ticker)
        alerts = [e for e in entries if e["score"] >= threshold]
        return {"ticker": ticker, "alerts": alerts, "ok": True}
    except Exception as ex:
        return {"ticker": ticker, "error": str(ex), "ok": False}


def run_scan(threshold: int) -> dict:
    """Run full scan with concurrent workers."""
    tickers = collect_all_tickers()
    total = len(tickers)
    print(f"Scanning {total} tickers (threshold={threshold}, workers={CONCURRENT_WORKERS})...")

    all_alerts = []
    errors = []
    scanned = 0
    done = 0

    # Process in batches of CONCURRENT_WORKERS
    for batch_start in range(0, total, CONCURRENT_WORKERS):
        batch = tickers[batch_start:batch_start + CONCURRENT_WORKERS]

        with ThreadPoolExecutor(max_workers=CONCURRENT_WORKERS) as executor:
            futures = {executor.submit(_scan_one, t, threshold): t for t in batch}
            for future in as_completed(futures, timeout=30):
                done += 1
                try:
                    result = future.result(timeout=15)
                    if result["ok"]:
                        scanned += 1
                        if result["alerts"]:
                            all_alerts.extend(result["alerts"])
                            print(f"  [{done}/{total}] {result['ticker']}: {len(result['alerts'])} alert(s) "
                                  f"(max score {max(a['score'] for a in result['alerts'])})")
                    else:
                        errors.append({"ticker": result["ticker"], "error": result.get("error", "")})
                except Exception:
                    errors.append({"ticker": "unknown", "error": "timeout"})

        # Rate limiting between batches
        time.sleep(config.DELAY_BETWEEN_BATCHES)

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


def _fmt_money(v: float) -> str:
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def _fmt_dte(d: int) -> str:
    if d <= 1:
        return '<span style="color:#f87171;font-weight:700">MANANA</span>'
    if d <= 3:
        return f'<span style="color:#f87171;font-weight:700">{d} dias</span>'
    if d <= 7:
        return f'<span style="color:#fbbf24;font-weight:600">{d} dias</span>'
    if d <= 14:
        return f'<span style="color:#fcd34d">{d} dias</span>'
    return f'<span style="color:#cbd5e1">{d} dias</span>'


def _score_color(score: float) -> str:
    if score >= 75:
        return "#f87171"
    if score >= 50:
        return "#fbbf24"
    return "#94a3b8"


def _score_label(score: float) -> str:
    if score >= 75:
        return "ALTA SOSPECHA"
    return "SOSPECHA MEDIA"


def _score_badge_bg(score: float) -> str:
    if score >= 75:
        return "background:#7f1d1d;color:#fca5a5"
    return "background:#78350f;color:#fcd34d"


def build_email_body(result: dict) -> str | None:
    """Build plain text email alert body for high-score tickers (>=60)."""
    critical = [ins for ins in result["insights"] if ins["max_score"] >= 60]
    if not critical:
        return None

    lines = []
    lines.append(f"Scan: {result['scan_time']}")
    lines.append(f"Tickers escaneados: {result['tickers_scanned']}")
    lines.append(f"Total alertas: {result['total_alerts']}")
    lines.append("")
    lines.append(f"{'='*60}")
    lines.append(f"ALERTAS (score >= 60)")
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


def build_email_html(result: dict) -> str | None:
    """Build HTML email matching the frontend dark theme. Returns None if no alerts >= 60."""
    critical = [ins for ins in result["insights"] if ins["max_score"] >= 60]
    if not critical:
        return None

    scan_time = result.get("scan_time", "")
    tickers_scanned = result.get("tickers_scanned", 0)
    tickers_with_alerts = result.get("tickers_with_alerts", 0)
    total_alerts = result.get("total_alerts", 0)
    high = sum(1 for ins in critical if ins["max_score"] >= 75)
    medium = len(critical) - high

    # Build insight cards HTML
    cards_html = ""
    for ins in critical:
        score = ins["max_score"]
        ticker = ins["ticker"]
        company = ins.get("company", ticker)
        spot = ins.get("spot", 0)
        notional = ins.get("total_notional", 0)
        alert_count = ins.get("alert_count", 0)
        alerts = ins.get("alerts", [])

        # Score badge
        badge_style = _score_badge_bg(score)
        badge_label = _score_label(score)
        badge_base = "display:inline-block;padding:3px 10px;border-radius:4px;font-size:10px;margin-right:6px;margin-bottom:4px"

        # Flow info from top alert
        top_alert = sorted(alerts, key=lambda a: a.get("score", 0), reverse=True)[0] if alerts else {}
        dp = top_alert.get("ticker_dominant_pct") or top_alert.get("dominant_pct", 0)
        flow_dir = top_alert.get("ticker_flow_direction") or top_alert.get("flow_direction", "")
        flow_badge = ""
        if dp >= 85:
            flow_badge = f'<span style="{badge_base};font-weight:600;background:#164e63;color:#67e8f9">Flujo {flow_dir} extremo {dp:.0f}%</span>'
        elif dp >= 75:
            flow_badge = f'<span style="{badge_base};background:#164e63;color:#67e8f9">Flujo {flow_dir} {dp:.0f}%</span>'

        # Contract rows
        rows_html = ""
        # Group by expiration
        by_exp: dict[str, list] = {}
        for a in alerts:
            exp = a.get("expiration", "?")
            by_exp.setdefault(exp, []).append(a)

        for exp, exp_alerts in by_exp.items():
            strikes = ", ".join(f"${a['strike']}" for a in exp_alerts)
            total_vol = sum(a.get("volume", 0) for a in exp_alerts)
            total_not = sum(a.get("notional", 0) for a in exp_alerts)
            dte = exp_alerts[0].get("dte", 0)
            top_a = sorted(exp_alerts, key=lambda a: a.get("score", 0), reverse=True)[0]
            reason = top_a.get("reason", "")[:100]
            a_dp = top_a.get("dominant_pct", 0)
            a_dir = top_a.get("flow_direction", "")
            calls_v = top_a.get("calls_volume", 0)
            puts_v = top_a.get("puts_volume", 0)
            flow_line = ""
            if a_dp >= 75:
                flow_color = "#67e8f9" if a_dp >= 85 else "#67e8f9aa"
                flow_weight = "font-weight:700" if a_dp >= 85 else ""
                flow_line = f'<div style="font-size:10px;color:{flow_color};{flow_weight}">{a_dir} {a_dp:.0f}% (C:{calls_v:,} P:{puts_v:,})</div>'

            rows_html += f'''
            <div style="border-top:1px solid #1e293b;padding:10px 0">
              <div style="margin-bottom:6px">
                <span style="color:#818cf8;font-family:monospace;font-size:13px;margin-right:12px">{exp}</span>
                <span style="font-size:11px">{_fmt_dte(dte)}</span>
              </div>
              <div style="margin-bottom:4px">
                <span style="color:#a5b4fc;font-weight:700;font-size:15px;margin-right:16px">{_fmt_money(total_not)}</span>
                <span style="color:#cbd5e1;font-size:12px;margin-right:16px">Strikes: {strikes}</span>
                <span style="color:#34d399;font-size:12px">Vol: {total_vol:,}</span>
              </div>
              {f'<div style="margin-bottom:4px">{flow_line}</div>' if flow_line else ''}
              <div style="color:#94a3b8;font-size:11px">{reason}</div>
            </div>'''

        cards_html += f'''
        <div style="background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:16px;margin-bottom:16px">
          <div style="margin-bottom:10px">
            <span style="font-size:18px;font-weight:700;color:#f8fafc;margin-right:10px">{ticker}</span>
            <span style="font-size:13px;color:#94a3b8;margin-right:8px">{company}</span>
            <span style="font-size:11px;color:#475569;margin-right:12px">@ ${spot:.2f}</span>
          </div>
          <div style="margin-bottom:10px">
            <span style="{badge_base};font-weight:600;{badge_style}">{badge_label}</span>
            <span style="{badge_base};font-weight:600;background:#312e81;color:#a5b4fc">Score {score:.0f}</span>
            {flow_badge}
          </div>
          <div style="font-size:12px;color:#64748b;margin-bottom:12px">
            {alert_count} contratos inusuales &nbsp;|&nbsp; Apuesta total: <strong style="color:#a5b4fc;font-size:13px">{_fmt_money(notional)}</strong>
          </div>
          <div>
            {rows_html}
          </div>
        </div>'''

    # Summary stat boxes
    html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#020617;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<div style="max-width:720px;margin:0 auto;padding:20px">

  <!-- Header -->
  <div style="text-align:center;margin-bottom:24px">
    <h1 style="color:#f8fafc;font-size:20px;margin:0 0 4px 0">Alpha Insights</h1>
    <p style="color:#64748b;font-size:12px;margin:0">Unusual Options Activity — {scan_time[:16].replace("T"," ")}</p>
  </div>

  <!-- Summary cards (inline-block for mobile wrap) -->
  <div style="text-align:center;margin-bottom:20px;font-size:0">
    <div style="display:inline-block;width:30%;min-width:100px;background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;margin:4px;vertical-align:top">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em">Escaneados</div>
      <div style="font-size:22px;font-weight:700;color:#818cf8;margin-top:4px">{tickers_scanned}</div>
    </div>
    <div style="display:inline-block;width:30%;min-width:100px;background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;margin:4px;vertical-align:top">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em">Con alertas</div>
      <div style="font-size:22px;font-weight:700;color:#f8fafc;margin-top:4px">{tickers_with_alerts}</div>
    </div>
    <div style="display:inline-block;width:30%;min-width:100px;background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;margin:4px;vertical-align:top">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em">Total alertas</div>
      <div style="font-size:22px;font-weight:700;color:#f8fafc;margin-top:4px">{total_alerts}</div>
    </div>
    <div style="display:inline-block;width:30%;min-width:100px;background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;margin:4px;vertical-align:top">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em">Alta sospecha</div>
      <div style="font-size:22px;font-weight:700;color:#f87171;margin-top:4px">{high}</div>
    </div>
    <div style="display:inline-block;width:30%;min-width:100px;background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center;margin:4px;vertical-align:top">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:0.05em">Sospecha media</div>
      <div style="font-size:22px;font-weight:700;color:#fbbf24;margin-top:4px">{medium}</div>
    </div>
  </div>

  <!-- Section title -->
  <h2 style="font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:12px">
    Insights — Sospechas de Insider Trading
  </h2>

  <!-- Insight cards -->
  {cards_html}

  <!-- Footer -->
  <div style="text-align:center;margin-top:24px;padding-top:16px;border-top:1px solid #1e293b">
    <p style="color:#475569;font-size:11px;margin:0">Alpha Insights — Insider Trading Detector</p>
    <p style="color:#334155;font-size:10px;margin:4px 0 0 0">Score ≥ 75 = Alta sospecha &nbsp;|&nbsp; Score ≥ 50 = Sospecha media</p>
  </div>

</div>
</body>
</html>'''

    return html


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scheduled insider trading scan")
    parser.add_argument("--threshold", type=int, default=40,
                        help="Minimum score threshold (default: 40)")
    args = parser.parse_args()

    result = run_scan(args.threshold)
    filepath = save_result(result)
    print_summary(result)
    print(f"\nResults saved to: {filepath}")

    # Write email alert files if critical alerts exist
    email_html = build_email_html(result)
    email_text = build_email_body(result)
    if email_html:
        html_path = SCHEDULED_DIR / "latest_alert.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(email_html)
        # Also save plain text fallback
        if email_text:
            txt_path = SCHEDULED_DIR / "latest_alert.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(email_text)
        print(f"\nCRITICAL ALERTS FOUND — email saved to {html_path}")
        # Set GitHub Actions output
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write("has_critical=true\n")
    else:
        print("\nNo critical alerts (score >= 60)")
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write("has_critical=false\n")
