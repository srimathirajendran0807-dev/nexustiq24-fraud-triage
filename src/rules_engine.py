"""
Deterministic risk-rule engine.

This module contains ZERO calls to any LLM. It takes a customer's
transaction history and a rule set, computes the customer's own behavioural
baseline (median spend, percentile spend, odd-hour rate, known payees,
known categories/channels/geos), and evaluates each transaction against the
five risk rules. Every flag it produces carries the exact transaction IDs
and the rule that triggered it, so the LLM layer downstream has nothing to
invent -- it only explains what this engine already found.

Keeping this separate from src/llm.py is a deliberate design choice: rule
logic must be auditable, reproducible, and testable without ever touching
the network.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any, List, Dict


def _parse_dt(txn: dict) -> datetime:
    return datetime.strptime(f"{txn['date']} {txn['time']}", "%Y-%m-%d %H:%M")


def _percentile(values: list, pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


def compute_baseline(transactions: List[dict]) -> Dict[str, Any]:
    """Derives this customer's own normal-behaviour profile from their history."""
    debits = [t for t in transactions if t["direction"] == "debit"]
    amounts = [t["amount"] for t in debits]

    odd_hour_count = sum(1 for t in debits if 0 <= _parse_dt(t).hour < 5)
    odd_hour_rate = odd_hour_count / len(debits) if debits else 0.0

    known_categories = {t["category"] for t in debits}
    known_channels = {t["channel"] for t in debits}
    known_geos = {t["geo"] for t in debits}

    payee_first_seen: Dict[str, datetime] = {}
    for t in sorted(debits, key=_parse_dt):
        payee_first_seen.setdefault(t["payee"], _parse_dt(t))

    if debits:
        span_days = max((max(_parse_dt(t) for t in debits) - min(_parse_dt(t) for t in debits)).days, 1)
        avg_monthly_outflow = sum(amounts) / span_days * 30
    else:
        avg_monthly_outflow = 0.0

    return {
        "median_amount": median(amounts) if amounts else 0.0,
        "p75_amount": _percentile(amounts, 0.75),
        "odd_hour_rate": odd_hour_rate,
        "known_categories": known_categories,
        "known_channels": known_channels,
        "known_geos": known_geos,
        "payee_first_seen": payee_first_seen,
        "avg_monthly_outflow": avg_monthly_outflow,
    }


def evaluate_rules(transactions: List[dict], rules: List[dict]) -> List[dict]:
    """Returns a list of findings. Each finding cites rule_id, matched
    txn_ids, and a machine-readable 'evidence' dict the LLM layer must ground
    its narrative in -- it should never need to touch raw transactions."""
    debits = [t for t in transactions if t["direction"] == "debit"]
    debits_sorted = sorted(debits, key=_parse_dt)
    baseline = compute_baseline(transactions)
    findings = []

    rule_ids = {r["rule_id"] for r in rules}

    if "R1_LARGE_TRANSFER" in rule_ids:
        threshold = max(5 * baseline["median_amount"], 50000)
        for t in debits_sorted:
            if t["amount"] > threshold:
                findings.append({
                    "rule_id": "R1_LARGE_TRANSFER",
                    "txn_ids": [t["txn_id"]],
                    "evidence": {
                        "amount": t["amount"],
                        "threshold_used": round(threshold, 2),
                        "customer_median_amount": round(baseline["median_amount"], 2),
                        "payee": t["payee"], "date": t["date"], "time": t["time"],
                    },
                })

    if "R2_NEW_PAYEE_BURST" in rule_ids:
        by_payee = defaultdict(list)
        for t in debits_sorted:
            by_payee[t["payee"]].append(t)
        for payee, txns in by_payee.items():
            first_seen = baseline["payee_first_seen"][payee]
            for i, t in enumerate(txns):
                window_txns = [x for x in txns if _parse_dt(x) <= _parse_dt(t) + timedelta(hours=72)
                                and _parse_dt(x) >= _parse_dt(t)]
                if len(window_txns) >= 3:
                    findings.append({
                        "rule_id": "R2_NEW_PAYEE_BURST",
                        "txn_ids": [x["txn_id"] for x in window_txns],
                        "evidence": {
                            "payee": payee,
                            "count_in_72h": len(window_txns),
                            "total_amount": round(sum(x["amount"] for x in window_txns), 2),
                            "first_transaction_with_payee": first_seen.strftime("%Y-%m-%d %H:%M"),
                        },
                    })
                    break

    if "R3_ODD_HOURS" in rule_ids and baseline["odd_hour_rate"] < 0.05:
        for t in debits_sorted:
            if 0 <= _parse_dt(t).hour < 5:
                findings.append({
                    "rule_id": "R3_ODD_HOURS",
                    "txn_ids": [t["txn_id"]],
                    "evidence": {
                        "time": t["time"], "date": t["date"], "amount": t["amount"],
                        "customer_historical_odd_hour_rate": round(baseline["odd_hour_rate"], 4),
                    },
                })

    if "R4_PATTERN_BREAK" in rule_ids:
        for t in debits_sorted:
            novel = (t["category"] not in baseline["known_categories"]
                     or t["channel"] not in baseline["known_channels"]
                     or t["geo"] not in baseline["known_geos"])
            if novel and t["amount"] > baseline["p75_amount"]:
                findings.append({
                    "rule_id": "R4_PATTERN_BREAK",
                    "txn_ids": [t["txn_id"]],
                    "evidence": {
                        "category": t["category"], "channel": t["channel"], "geo": t["geo"],
                        "amount": t["amount"],
                        "customer_p75_amount": round(baseline["p75_amount"], 2),
                        "known_categories": sorted(baseline["known_categories"]),
                    },
                })

    if "R5_RAPID_DRAIN" in rule_ids:
        for i, t in enumerate(debits_sorted):
            window = [x for x in debits_sorted
                      if _parse_dt(t) <= _parse_dt(x) <= _parse_dt(t) + timedelta(hours=24)]
            total = sum(x["amount"] for x in window)
            if len(window) >= 3 and total > 0.6 * baseline["avg_monthly_outflow"] and baseline["avg_monthly_outflow"] > 0:
                findings.append({
                    "rule_id": "R5_RAPID_DRAIN",
                    "txn_ids": [x["txn_id"] for x in window],
                    "evidence": {
                        "count_in_24h": len(window),
                        "total_amount": round(total, 2),
                        "avg_monthly_outflow": round(baseline["avg_monthly_outflow"], 2),
                    },
                })
                break

    return _dedupe_findings(findings)


def _dedupe_findings(findings: List[dict]) -> List[dict]:
    seen = set()
    unique = []
    for f in findings:
        key = (f["rule_id"], tuple(sorted(f["txn_ids"])))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def investigate(transactions: List[dict], rules: List[dict]) -> dict:
    """Top-level deterministic entry point used by the API layer."""
    findings = evaluate_rules(transactions, rules)
    txn_index = {t["txn_id"]: t for t in transactions}
    return {
        "has_findings": len(findings) > 0,
        "findings": findings,
        "txn_index": {fid: txn_index[fid] for f in findings for fid in f["txn_ids"]},
    }