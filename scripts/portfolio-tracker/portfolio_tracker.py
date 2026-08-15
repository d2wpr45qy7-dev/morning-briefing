#!/usr/bin/env python3
"""
portfolio_tracker.py — portfolio-aware successor to financials.py.

WHAT THIS DOES:
  - Reads a market snapshot (same asset schema financials.py used — you still
    have to gather that data yourself via web_fetch/search, since this
    environment can't hit live finance APIs directly).
  - Merges it against portfolio_config.json (your actual share counts / cost
    basis) to compute position value, unrealized $ and %, and allocation.
  - Appends each day's snapshot to history.jsonl so trend/momentum is
    computed from real history, not a single day's number.
  - Evaluates watch_rules.json against current + historical data and reports
    which conditions are met.

WHAT THIS DOES NOT DO:
  - It does not tell you to buy or sell anything. Every rule it evaluates is
    one YOU defined with YOUR numbers in watch_rules.json. Output is phrased
    as "condition met / not met," never as a recommendation. If a value in a
    rule is null, the tracker will refuse to evaluate that condition and will
    say so explicitly rather than silently skipping it.

INPUT SCHEMA (market snapshot JSON, passed as argv[1]):
{
  "date": "YYYY-MM-DD",
  "assets": [
    {
      "symbol": "BLK", "price": 1042.10, "day_change_pct": -0.8,
      "wk52_low": 780.00, "wk52_high": 1150.00,
      "analyst_avg_target": 1080.00, "note": "optional"
    },
    ... one entry per holding in portfolio_config.json ...
  ]
}

USAGE:
  python3 portfolio_tracker.py snapshot.json
  python3 portfolio_tracker.py snapshot.json --config portfolio_config.json \
      --rules watch_rules.json --history history.jsonl
"""
import argparse
import json
import sys
import os
import datetime


# ---------- shared math helpers (same logic as financials.py) ----------

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
    if target is None or not price:
        return None
    return (target - price) / price * 100.0


# ---------- loading ----------

def load_json(path, required=True):
    if not os.path.exists(path):
        if required:
            print(f"ERROR: required file not found: {path}", file=sys.stderr)
            sys.exit(1)
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_history(path):
    """history.jsonl: one JSON object per line, {symbol, date, price}."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip corrupt lines rather than crash
    return rows


def append_history(path, date_str, assets):
    with open(path, "a", encoding="utf-8") as f:
        for a in assets:
            f.write(json.dumps({"symbol": a["symbol"], "date": date_str, "price": a["price"]}) + "\n")


def momentum_from_history(history, symbol, current_price, lookback_days=7):
    """Average day-over-day % change over the last N logged points for this
    symbol, INCLUDING today. Returns None if there isn't enough history yet —
    this is intentional: a momentum figure computed from one or two points
    is noise, not signal, and would be worse than saying 'not enough data.'"""
    points = sorted(
        [h for h in history if h["symbol"] == symbol],
        key=lambda h: h["date"],
    )
    points = points[-(lookback_days - 1):] if points else []
    prices = [p["price"] for p in points] + [current_price]
    if len(prices) < 3:
        return None
    changes = [
        (prices[i] - prices[i - 1]) / prices[i - 1] * 100.0
        for i in range(1, len(prices))
        if prices[i - 1]
    ]
    if not changes:
        return None
    return sum(changes) / len(changes)


# ---------- portfolio math ----------

def enrich_with_portfolio(assets, holdings):
    holdings_by_symbol = {h["symbol"]: h for h in holdings}
    total_value = 0.0
    enriched = []

    # first pass: compute position values so we can get allocation %
    for a in assets:
        h = holdings_by_symbol.get(a["symbol"])
        a = dict(a)
        if h and h.get("shares"):
            a["shares"] = h["shares"]
            a["cost_basis_per_share"] = h.get("cost_basis_per_share")
            a["position_value"] = a["price"] * h["shares"]
            total_value += a["position_value"]
        else:
            a["shares"] = None
            a["cost_basis_per_share"] = None
            a["position_value"] = None
        enriched.append(a)

    for a in enriched:
        if a["position_value"] is not None and total_value > 0:
            a["allocation_pct"] = a["position_value"] / total_value * 100.0
        else:
            a["allocation_pct"] = None

        cb = a.get("cost_basis_per_share")
        if cb:
            a["unrealized_pct"] = (a["price"] - cb) / cb * 100.0
            a["unrealized_dollars"] = (a["price"] - cb) * (a["shares"] or 0)
        else:
            a["unrealized_pct"] = None
            a["unrealized_dollars"] = None

        a["range_position_pct"] = range_position_pct(a["price"], a.get("wk52_low"), a.get("wk52_high"))
        a["analyst_upside_pct"] = analyst_upside_pct(a["price"], a.get("analyst_avg_target"))

    return enriched, total_value


# ---------- rules engine ----------

def get_condition_actual_value(cond, asset, momentum):
    t = cond["type"]
    if t == "price_target":
        return asset["price"]
    if t == "pct_from_cost":
        return asset.get("unrealized_pct")
    if t == "technical":
        signal = cond.get("signal", "range_position_pct")
        if signal == "range_position_pct":
            return asset.get("range_position_pct")
        if signal == "momentum_pct":
            return momentum
        return None
    return None


def evaluate_condition(cond, actual):
    if cond.get("value") is None:
        return None, "UNSET — no value defined in watch_rules.json for this condition"
    if actual is None:
        return None, "NO DATA — couldn't compute this from the snapshot/history given"
    op = cond["operator"]
    v = cond["value"]
    ops = {
        "<=": actual <= v, ">=": actual >= v,
        "<": actual < v, ">": actual > v, "==": actual == v,
    }
    if op not in ops:
        return None, f"UNKNOWN OPERATOR '{op}'"
    return ops[op], f"actual={actual:.2f}, threshold {op} {v}"


def evaluate_rules(rules, assets_by_symbol, history, date_str):
    results = {}
    for symbol, rule in rules.items():
        if symbol.startswith("_"):
            continue
        asset = assets_by_symbol.get(symbol)
        if not asset:
            results[symbol] = {"error": f"'{symbol}' not present in today's snapshot"}
            continue

        momentum = momentum_from_history(history, symbol, asset["price"])
        cond_results = []
        for cond in rule["conditions"]:
            actual = get_condition_actual_value(cond, asset, momentum)
            met, detail = evaluate_condition(cond, actual)
            cond_results.append({
                "type": cond["type"],
                "description": cond.get("description", ""),
                "met": met,
                "detail": detail,
            })

        determinable = [c["met"] for c in cond_results if c["met"] is not None]
        if not determinable:
            triggered = None
        elif rule["logic"] == "ALL":
            triggered = all(determinable) and len(determinable) == len(cond_results)
        else:  # ANY
            triggered = any(determinable)

        results[symbol] = {
            "watch_type": rule.get("watch_type", "exit"),
            "logic": rule["logic"],
            "conditions": cond_results,
            "triggered": triggered,
        }
    return results


# ---------- output ----------

def render_summary(date_str, enriched, total_value, rule_results):
    lines = [f"PORTFOLIO TRACKER — {date_str}", ""]
    for a in enriched:
        pv = fmt_money(a["position_value"]) if a["position_value"] is not None else "n/a (no share count set)"
        alloc = fmt_pct(a["allocation_pct"], 1, sign=False) if a["allocation_pct"] is not None else "n/a"
        unreal = fmt_pct(a["unrealized_pct"]) if a["unrealized_pct"] is not None else "n/a (no cost basis set)"
        lines.append(
            f"{a['symbol']}: {fmt_money(a['price'])} ({fmt_pct(a.get('day_change_pct'))} today) | "
            f"position: {pv} ({alloc} of tracked portfolio) | unrealized: {unreal}"
        )
    lines.append("")
    lines.append(f"Total tracked portfolio value: {fmt_money(total_value)}" if total_value else
                 "Total tracked portfolio value: n/a — add shares to portfolio_config.json")
    lines.append("")
    lines.append("WATCH RULES")
    for symbol, res in rule_results.items():
        if "error" in res:
            lines.append(f"{symbol}: {res['error']}")
            continue
        status = {True: "TRIGGERED", False: "not triggered", None: "INCOMPLETE (unset/missing data)"}[res["triggered"]]
        lines.append(f"{symbol} [{res['watch_type']}, {res['logic']}] — {status}")
        for c in res["conditions"]:
            flag = {True: "MET", False: "not met", None: c["detail"].split(" —")[0]}[c["met"]]
            lines.append(f"  - {c['type']}: {flag} ({c['detail']})")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot", help="path to market snapshot JSON")
    ap.add_argument("--config", default="portfolio_config.json")
    ap.add_argument("--rules", default="watch_rules.json")
    ap.add_argument("--history", default="history.jsonl")
    args = ap.parse_args()

    snapshot = load_json(args.snapshot)
    config = load_json(args.config)
    rules = load_json(args.rules, required=False) or {}

    date_str = snapshot.get("date", datetime.date.today().isoformat())
    history = load_history(args.history)

    enriched, total_value = enrich_with_portfolio(snapshot["assets"], config["holdings"])
    assets_by_symbol = {a["symbol"]: a for a in enriched}

    rule_results = evaluate_rules(rules, assets_by_symbol, history, date_str)

    append_history(args.history, date_str, enriched)

    output = {
        "date": date_str,
        "assets": enriched,
        "total_value": total_value,
        "watch_rules": rule_results,
    }
    print(json.dumps(output, indent=2))
    print("\n" + "=" * 60 + "\n", file=sys.stderr)
    print(render_summary(date_str, enriched, total_value, rule_results), file=sys.stderr)


if __name__ == "__main__":
    main()
