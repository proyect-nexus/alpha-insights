"""
AI Analysis Layer — Claude API integration for insider trading analysis.

Analyzes tickers with high suspicion scores (>=60) to determine:
1. What could be producing the unusual options activity
2. Whether it makes sense to join the trade
"""

import os
import asyncio
from datetime import datetime, timedelta

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

import config

# Cache: key -> {result, timestamp}
_analysis_cache: dict[str, dict] = {}
CACHE_TTL = 3600  # 1 hour


def _cache_key(ticker: str, max_score: float, total_notional: float) -> str:
    return f"{ticker}_{int(max_score)}_{int(total_notional)}"


def _is_available() -> tuple[bool, str]:
    if not HAS_ANTHROPIC:
        return False, "anthropic package not installed"
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY not configured"
    return True, ""


def _build_prompt(ticker: str, insight: dict, context: dict) -> str:
    """Build the analysis prompt with all available data."""
    company = insight.get("company", ticker)
    spot = insight.get("spot", 0)
    alerts = insight.get("alerts", [])
    max_score = insight.get("max_score", 0)
    total_notional = insight.get("total_notional", 0)

    # Format contracts
    contracts_text = []
    for a in sorted(alerts, key=lambda x: x.get("score", 0), reverse=True):
        contracts_text.append(
            f"  - Strike ${a.get('strike', 0)} | Exp {a.get('expiration', '?')} ({a.get('dte', '?')}d) | "
            f"OTM {a.get('otm_pct', 0):.1f}% | Vol {a.get('volume', 0):,} | OI {a.get('open_interest', 0):,} | "
            f"V/OI {a.get('vol_oi_ratio', 0):.1f}x | Notional ${a.get('notional', 0):,.0f} | Score {a.get('score', 0):.0f}"
        )

    # Aggregate signals
    top = alerts[0] if alerts else {}
    flow_dir = top.get("ticker_flow_direction", top.get("flow_direction", ""))
    flow_pct = top.get("ticker_dominant_pct", top.get("dominant_pct", 0))
    oi_conc = top.get("oi_concentration", 0)
    vol_baseline = top.get("vol_vs_baseline", 0)

    # Context
    ctx = context or {}
    reddit_hype = ctx.get("reddit", {}).get("hype_level", "none")
    reddit_mentions = ctx.get("reddit", {}).get("total_mentions", 0)
    has_earnings = ctx.get("earnings", {}).get("has_upcoming_earnings", False)
    earnings_date = ctx.get("earnings", {}).get("earnings_date", "")
    days_to_earnings = ctx.get("earnings", {}).get("days_to_earnings", "")

    prompt = f"""Analiza esta actividad inusual de opciones detectada en {ticker} ({company}):

**Acción**: {ticker} ({company}) @ ${spot:.2f}
**Score de sospecha**: {max_score:.0f}/100
**Apuesta total (notional)**: ${total_notional:,.0f}
**Contratos inusuales**: {len(alerts)}

**Contratos inusuales (ordenados por score)**:
{chr(10).join(contracts_text)}

**Señales agregadas**:
- Flujo direccional: {flow_dir} {flow_pct:.0f}%
- Concentración de OI: {oi_conc:.0f}%
- Volumen vs baseline: {vol_baseline:.1f}x

**Contexto público**:
- Hype en Reddit: {reddit_hype} ({reddit_mentions} menciones esta semana)
- Earnings próximos: {"Sí — " + str(earnings_date) + " (" + str(days_to_earnings) + " días)" if has_earnings else "No"}

Responde estas dos preguntas:

1. **¿Qué puede estar produciendo estas apuestas?** Considera: conocimiento insider antes de M&A/FDA/earnings, cobertura o reposicionamiento institucional, momentum retail inusual, rotación sectorial o jugadas técnicas de breakout. Sé específico sobre qué escenario encaja mejor con el patrón de datos.

2. **¿Tiene sentido sumarse a esta apuesta?** Considera el riesgo/beneficio dado las primas de las opciones, el tiempo hasta expiración y qué tan OTM están los strikes. Si sí, sugiere cómo entrar. Si no, explica por qué.

Termina con un nivel de confianza (alta/media/baja) para tu hipótesis de insider trading."""

    return prompt


SYSTEM_PROMPT = """Eres un analista experto en flujo de opciones especializado en detectar actividad inusual que pueda indicar insider trading o posicionamiento informado.

Reglas:
- Sé conciso: 3-5 oraciones por pregunta máximo
- Sé directo: da una recomendación clara, no respuestas ambiguas
- Usa los datos: referencia contratos específicos, strikes y métricas
- Considera múltiples explicaciones pero ordénalas por probabilidad
- Siempre menciona los factores de riesgo clave
- Responde SIEMPRE en español
- Formatea tu respuesta con headers claros usando markdown"""


async def analyze_ticker(ticker: str, insight: dict, context: dict) -> dict:
    """Analyze a single ticker's unusual activity using Claude API."""
    available, reason = _is_available()
    if not available:
        return {"available": False, "reason": reason}

    # Check cache
    cache_key = _cache_key(ticker, insight.get("max_score", 0), insight.get("total_notional", 0))
    if cache_key in _analysis_cache:
        cached = _analysis_cache[cache_key]
        if datetime.now() - cached["timestamp"] < timedelta(seconds=CACHE_TTL):
            return cached["result"]

    try:
        client = anthropic.AsyncAnthropic()
        prompt = _build_prompt(ticker, insight, context)

        message = await client.messages.create(
            model=config.AI_ANALYSIS_MODEL,
            max_tokens=config.AI_ANALYSIS_MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        text = message.content[0].text if message.content else ""

        # Extract confidence from the response text
        confidence = "media"
        text_lower = text.lower()
        if "confianza: alta" in text_lower or "confianza:**alta" in text_lower or "**alta**" in text_lower or "nivel de confianza: alta" in text_lower or "confidence: high" in text_lower:
            confidence = "alta"
        elif "confianza: baja" in text_lower or "confianza:**baja" in text_lower or "**baja**" in text_lower or "nivel de confianza: baja" in text_lower or "confidence: low" in text_lower:
            confidence = "baja"

        result = {
            "available": True,
            "analysis": text,
            "confidence": confidence,
            "analyzed_at": datetime.now().isoformat(),
            "model": config.AI_ANALYSIS_MODEL,
            "ticker": ticker,
        }

        _analysis_cache[cache_key] = {"result": result, "timestamp": datetime.now()}
        return result

    except Exception as e:
        return {
            "available": True,
            "error": str(e),
            "analyzed_at": datetime.now().isoformat(),
        }


async def analyze_alerts(alerts: list[dict], insights: list[dict], context_map: dict) -> None:
    """Analyze all qualifying tickers and attach results to insights/alerts."""
    available, reason = _is_available()
    if not available:
        return

    for ins in insights:
        if ins.get("max_score", 0) < config.AI_ANALYSIS_THRESHOLD:
            continue

        ticker = ins["ticker"]
        ctx = context_map.get(ticker, {})
        result = await analyze_ticker(ticker, ins, ctx)
        ins["ai_analysis"] = result

        # Also attach to each alert of this ticker
        for a in alerts:
            if a["ticker"] == ticker:
                a["ai_analysis"] = result
