"""
agent_c_gl_matcher.py
Agent C — GL Matching.

Deterministic backbone: match each bank transaction to GL entries in three
passes of decreasing certainty:
  1. reference  — exact reference + amount within tolerance        (conf 1.0)
  2. amount+date — same amount within tolerance, date within window (conf 0.9)
  3. fuzzy description — rapidfuzz/difflib >= threshold + amount    (conf ~score)

rapidfuzz is used when installed; otherwise difflib provides the same 0-1 score.
Writes match_result.json.
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

from file_utils import read_json, read_csv_rows, write_json, append_log
from schemas import MatchResult, MatchPair


def _log(run_dir: str, msg: str) -> None:
    append_log(os.path.join(run_dir, "logs", "agent_c.log"), msg)


def _d(x) -> Decimal:
    return Decimal(str(x))


def _parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def _similarity(a: str, b: str) -> float:
    a, b = a.upper().strip(), b.upper().strip()
    try:
        from rapidfuzz import fuzz
        return fuzz.token_sort_ratio(a, b) / 100.0
    except Exception:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()


def run(run_dir: str, policy: dict) -> None:
    print("[Agent C] Starting — GL matching...")
    _log(run_dir, "=== Agent C: GL Matching ===")

    m = policy.get("matching", {})
    amount_tol_pct = _d(m.get("amount_tolerance_pct", 0.01))
    date_window = int(m.get("timing_window_days", 5))
    fuzz_threshold = float(m.get("fuzzy_description_threshold", 0.85))

    txns = read_json(os.path.join(run_dir, "transactions.json"))
    ctx = read_json(os.path.join(run_dir, "context_packet.json"))
    gl_path = ctx["inputs"]["gl_export"]["path"]
    gl = read_csv_rows(gl_path)

    gl_by_id = {g["gl_id"]: g for g in gl}
    matched: list[MatchPair] = []
    used_gl: set[str] = set()
    unmatched_bank: list[str] = []

    def amount_close(a, b) -> bool:
        a, b = _d(a), _d(b)
        tol = abs(a) * amount_tol_pct
        return abs(a - b) <= tol

    for t in txns:
        b_ref = (t.get("reference") or "").strip().upper()
        b_amt = t["amount"]
        b_date = _parse_date(t["date"])
        hit = None

        # Pass 1: reference + amount
        if b_ref:
            for g in gl:
                if g["gl_id"] in used_gl:
                    continue
                if (g.get("reference") or "").strip().upper() == b_ref and amount_close(b_amt, g["amount"]):
                    hit = (g["gl_id"], "reference", 1.0)
                    break

        # Pass 2: amount + date window
        if hit is None:
            for g in gl:
                if g["gl_id"] in used_gl:
                    continue
                if amount_close(b_amt, g["amount"]):
                    try:
                        delta = abs((b_date - _parse_date(g["date"])).days)
                    except Exception:
                        continue
                    if delta <= date_window:
                        hit = (g["gl_id"], "amount_date", 0.9)
                        break

        # Pass 3: fuzzy description + amount
        if hit is None:
            best = (None, 0.0)
            for g in gl:
                if g["gl_id"] in used_gl or not amount_close(b_amt, g["amount"]):
                    continue
                score = _similarity(t.get("description", ""), g.get("description", ""))
                if score > best[1]:
                    best = (g["gl_id"], score)
            if best[0] and best[1] >= fuzz_threshold:
                hit = (best[0], "fuzzy_description", round(best[1], 2))

        if hit:
            gl_id, method, conf = hit
            used_gl.add(gl_id)
            matched.append(MatchPair(
                bank_txn=t["txn_id"], gl_entries=[gl_id],
                match_type="1:1", method=method, confidence=conf,
            ))
            _log(run_dir, f"matched {t['txn_id']} -> {gl_id} via {method} (conf {conf})")
        else:
            unmatched_bank.append(t["txn_id"])
            _log(run_dir, f"unmatched bank txn {t['txn_id']}")

    unmatched_gl = [g["gl_id"] for g in gl if g["gl_id"] not in used_gl]
    match_rate = round(len(matched) / len(txns), 4) if txns else 0.0

    result = MatchResult(
        matched=matched,
        unmatched_bank=unmatched_bank,
        unmatched_gl=unmatched_gl,
        summary={
            "bank_txn_count": len(txns),
            "gl_entry_count": len(gl),
            "matched_count": len(matched),
            "match_rate": match_rate,
        },
    )
    write_json(os.path.join(run_dir, "match_result.json"), result.model_dump())
    _log(run_dir, f"match_rate={match_rate} unmatched_bank={len(unmatched_bank)} "
                  f"unmatched_gl={len(unmatched_gl)}")
    print(f"[Agent C] Done — match rate {match_rate:.0%}.")
