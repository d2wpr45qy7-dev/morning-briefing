#!/usr/bin/env python3
"""
financials.py — quantitative backbone for the Morning Briefing's Financials section.

This module does NOT fetch data itself (the sandbox's network allowlist blocks
direct API/HTTP calls to finance endpoints). Instead, each morning the briefing
run gathers that day's figures via Google Finance quote pages (web_fetch) for
equities/crypto and a web search for gold spot price, drops them into a JSON
file matching INPUT SCHEMA below, and calls this script to compute the
quantitative signals and render the HTML + plain-text output.

INPUT SCHEMA (JSON file passed as argv[1]):
{
  "date": "YYYY-MM-DD",
  "assets": [
    {
      "symbol": "AAPL", "name": "Apple Inc.", "category": "equity",
      "price": 305.93, "day_change_pct": 0.22,
      "wk52_low": 223.78, "wk52_high": 344.57,
      "analyst_avg_target": 333.99, "analyst_high_target": 400.00,
      "analyst_low_target": 245.00, "pe_ratio": 35.07,
      "note": "optional one-line qualitative note from that day's news flow"
    },
    ... one entry each for AAPL, LMT, BLK, XOM (category "equity") ...
    { "symbol": "BTC-USD", "name": "Bitcoin", "category": "crypto",
      "price": 62997.32, "day_change_pct": 0.04, "market_cap": "1.26T",
      "note": "..." },
    { "symbol": "XAU", "name": "Gold (spot)", "category": "commodity",
      "price": 4373.09, "day_change_pct": null, "note": "..." }
  ],
  "geopolitical_flags": ["defense", "energy"]   # optional hints from that day's
                                                  # news (e.g. Mideast tension,
                                                  # Fed decision, tariff news)
                                                  # used to color the aggregate read
}

OUTPUT: prints a JSON object to stdout with:
  - "assets": input assets enriched with computed fields (range_position_pct,
    analyst_upside_pct, trend_signal)
  - "aggregate": macro-level read (risk_sentiment, defense_energy_note, summary)
  - "html_light": ready-to-embed HTML snippet (light palette) for the PDF
  - "html_dark": same snippet, dark palette
  - "plain_text": plain-text digest chunk for the email

Usage:
  python3 financials.py input.json > output.json
"""
import json
import sys
import datetime


def fmt_money(x, decimals=2):
    if x is None:
        return "n/a"
    return f"${x:,.{decimals}f}"


def fmt_pct(x, decimals=2, sign=True):
    if x is None:
        return "n/a"
    s = "+" if (sign and x > 0) else ""
    return f"{s}{x:.{decimals}f}%"


def range_position_pct(price, lo, hi):
    if lo is None or hi is None or hi == lo:
        return None
    return max(0.0, min(100.0, (price - lo) / (hi - lo) * 100.0))


def analyst_upside_pct(price, target):
    if target is None or price == 0:
        return None
    return (target - price) / price * 100.0


def trend_signal(asset):
    """Rule-based label — deliberately simple and legible, not a black box."""
    cat = asset.get("category")
    chg = asset.get("day_change_pct")
    rp = asset.get("range_position_pct")
    up = asset.get("analyst_upside_pct")

    if cat == "equity":
        if rp is not None and rp >= 80 and (chg or 0) >= 0:
            base = "Near 52-week highs, momentum intact"
        elif rp is not None and rp <= 30 and (chg or 0) <= 0:
            base = "Trading near 52-week lows"
        elif rp is not None and rp >= 55:
            base = "Upper half of 52-week range"
        elif rp is not None:
            base = "Lower half of 52-week range"
        else:
            base = "Range unclear"
        if up is not None:
            if up >= 8:
                base += "; Street sees meaningful upside to target"
            elif up <= -5:
                base += "; trading above Street's average target"
        return base

    if cat == "crypto":
        if chg is None:
            return "Flat / no clear signal"
        if chg > 2:
            return "Sharp risk-on move"
        if chg < -2:
            return "Sharp risk-off move"
        return "Consolidating"

    if cat == "commodity":
        if chg is None:
            return "Watch for safe-haven bid"
        if chg > 0.5:
            return "Safe-haven bid building"
        if chg < -0.5:
            return "Safe-haven bid fading"
        return "Holding steady"

    return "n/a"


def compute_aggregate(assets, flags):
    equities = [a for a in assets if a["category"] == "equity"]
    crypto = next((a for a in assets if a["category"] == "crypto"), None)
    gold = next((a for a in assets if a["category"] == "commodity"), None)

    eq_changes = [a.get("day_change_pct") for a in equities if a.get("day_change_pct") is not None]
    eq_avg_change = sum(eq_changes) / len(eq_changes) if eq_changes else None

    gold_chg = gold.get("day_change_pct") if gold else None
    crypto_chg = crypto.get("day_change_pct") if crypto else None

    # risk sentiment: gold + bitcoin direction relative to equities
    if gold_chg is not None and crypto_chg is not None and eq_avg_change is not None:
        if gold_chg > 0 and crypto_chg < 0 and eq_avg_change >= 0:
            risk = "Mixed: gold bid while crypto lags equities — a hedging flow, not full risk-off."
        elif gold_chg > 0 and crypto_chg > 0 and eq_avg_change < 0:
            risk = "Risk-off: both gold and bitcoin catching a bid while equities soften."
        elif gold_chg <= 0 and crypto_chg > 0 and eq_avg_change > 0:
            risk = "Risk-on: equities and crypto both firm, gold's safe-haven bid easing."
        else:
            risk = "No dominant cross-asset signal today — moves look idiosyncratic, not macro-driven."
    else:
        risk = "Insufficient data for a cross-asset read."

    defense_note = None
    lmt = next((a for a in equities if a["symbol"] == "LMT"), None)
    if lmt and "defense" in (flags or []):
        chg = lmt.get("day_change_pct")
        if chg is not None and chg > 1:
            defense_note = "Lockheed's move outpacing the broader tape lines up with the day's defense/security headlines — geopolitical risk premium building into defense names."

    energy_note = None
    xom = next((a for a in equities if a["symbol"] == "XOM"), None)
    if xom and "energy" in (flags or []):
        chg = xom.get("day_change_pct")
        if chg is not None and chg > 0.5:
            energy_note = "Exxon firm alongside today's energy-relevant headlines — watch for a crude-driven, not fundamentals-driven, move."

    return {
        "risk_sentiment": risk,
        "defense_note": defense_note,
        "energy_note": energy_note,
        "equity_avg_change_pct": eq_avg_change,
    }


def enrich(assets):
    out = []
    for a in assets:
        a = dict(a)
        if a["category"] == "equity":
            a["range_position_pct"] = range_position_pct(a["price"], a.get("wk52_low"), a.get("wk52_high"))
            a["analyst_upside_pct"] = analyst_upside_pct(a["price"], a.get("analyst_avg_target"))
        else:
            a["range_position_pct"] = None
            a["analyst_upside_pct"] = None
        a["trend_signal"] = trend_signal(a)
        out.append(a)
    return out


def render_html(assets, aggregate, date_str, theme="light"):
    palette = {
        "light": {"card": "#f1ece0", "border": "#a3222b", "text": "#1c1712", "muted": "#5c5346"},
        "dark":  {"card": "#241f18", "border": "#e2795f", "text": "#ece5d8", "muted": "#b3a998"},
    }[theme]

    rows = []
    for a in assets:
        chg = a.get("day_change_pct")
        chg_str = fmt_pct(chg) if chg is not None else "n/a"
        price_str = fmt_money(a["price"], 2 if a["category"] != "crypto" else 0)
        extra = ""
        if a["category"] == "equity":
            rp = a.get("range_position_pct")
            up = a.get("analyst_upside_pct")
            extra = f"52-wk range position: {rp:.0f}%. Analyst avg. target upside: {fmt_pct(up)}." if rp is not None else ""
        rows.append(
            f"<div class='fin-row'><b>{a['symbol']}</b> ({a['name']}) &mdash; {price_str}, {chg_str} today. "
            f"<i>{a['trend_signal']}.</i> {extra}</div>"
        )

    agg_lines = [f"<div>{aggregate['risk_sentiment']}</div>"]
    if aggregate.get("defense_note"):
        agg_lines.append(f"<div>{aggregate['defense_note']}</div>")
    if aggregate.get("energy_note"):
        agg_lines.append(f"<div>{aggregate['energy_note']}</div>")

    html = (
        f"<div class='fin-block'>"
        f"{''.join(rows)}"
        f"</div>"
        f"<div class='fin-callout'>"
        f"<span class='fin-callout-tag'>Market Predictions &amp; Moves</span>"
        f"{''.join(agg_lines)}"
        f"<div class='fin-disclaimer'>Informational market read compiled {date_str}, not personalized financial advice.</div>"
        f"</div>"
    )
    return html


def render_text(assets, aggregate, date_str):
    lines = [f"FINANCIALS ({date_str})"]
    for a in assets:
        chg = fmt_pct(a.get("day_change_pct")) if a.get("day_change_pct") is not None else "n/a"
        lines.append(f"- {a['symbol']}: {fmt_money(a['price'], 2 if a['category'] != 'crypto' else 0)} ({chg}) - {a['trend_signal']}")
    lines.append("")
    lines.append("MARKET PREDICTIONS & MOVES")
    lines.append(aggregate["risk_sentiment"])
    if aggregate.get("defense_note"):
        lines.append(aggregate["defense_note"])
    if aggregate.get("energy_note"):
        lines.append(aggregate["energy_note"])
    lines.append("(Informational, not personalized financial advice.)")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("usage: financials.py input.json", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    date_str = data.get("date", datetime.date.today().isoformat())
    assets = enrich(data["assets"])
    aggregate = compute_aggregate(assets, data.get("geopolitical_flags"))

    result = {
        "date": date_str,
        "assets": assets,
        "aggregate": aggregate,
        "html_light": render_html(assets, aggregate, date_str, "light"),
        "html_dark": render_html(assets, aggregate, date_str, "dark"),
        "plain_text": render_text(assets, aggregate, date_str),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
