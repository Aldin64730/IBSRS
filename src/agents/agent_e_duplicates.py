"""
agent_e_duplicates.py
Agent E — Duplicate Detection.

Deterministic: compare bank transactions pairwise on amount (within policy
variance), reference/description, and date proximity (within policy window).
Flags interface-error style double-entries and suggests a reversal. Emits:
  - duplicates.json
  - findings/agent_e_duplicates.json
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal

from file_utils import read_json, write_json, append_log
from schemas import Finding


def _log(run_dir: str, msg: str) -> None:
    append_log(os.path.join(run_dir, "logs", "agent_e.log"), msg)


def _parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


def run(run_dir: str, policy: dict) -> None:
    print("[Agent E] Starting — duplicate detection...")
    _log(run_dir, "=== Agent E: Duplicate Detection ===")

    th = policy.get("thresholds", {})
    amount_variance = Decimal(str(th.get("duplicate_amount_variance", 0.0)))
    date_window = int(th.get("duplicate_date_window_days", 3))

    txns = read_json(os.path.join(run_dir, "transactions.json"))

    pairs: list[dict] = []
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    fid = 100  # Agent E findings start at F-0101 to avoid colliding with D's F-00xx

    for i in range(len(txns)):
        for j in range(i + 1, len(txns)):
            a, b = txns[i], txns[j]
            amt_a, amt_b = Decimal(str(a["amount"])), Decimal(str(b["amount"]))
            if abs(amt_a - amt_b) > amount_variance:
                continue
            same_ref = (a.get("reference") or "_a") == (b.get("reference") or "_b")
            same_desc = a.get("description", "").upper() == b.get("description", "").upper()
            if not (same_ref or same_desc):
                continue
            try:
                delta = abs((_parse_date(a["date"]) - _parse_date(b["date"])).days)
            except Exception:
                continue
            if delta > date_window:
                continue

            key = tuple(sorted((a["txn_id"], b["txn_id"])))
            if key in seen:
                continue
            seen.add(key)

            fid += 1
            finding_id = f"F-{fid:04d}"
            confidence = 0.98 if (same_ref and same_desc) else 0.85
            pairs.append({
                "original": a["txn_id"], "duplicate": b["txn_id"],
                "amount": f"{amt_b:.2f}", "date_delta_days": delta,
                "match_on": "reference+description" if (same_ref and same_desc)
                            else ("reference" if same_ref else "description"),
                "suggested_reversal": True,
            })
            findings.append(Finding(
                finding_id=finding_id,
                type="duplicate_transaction",
                severity="high",
                confidence=confidence,
                txn_ids=[a["txn_id"], b["txn_id"]],
                summary=f"Possible duplicate: {b['txn_id']} repeats {a['txn_id']} "
                        f"({amt_b}) within {delta} day(s).",
                recommended_action="create_reversal_entry",
                evidence=[
                    {"file": a["source"]["file"], "row": a["source"]["row"]},
                    {"file": b["source"]["file"], "row": b["source"]["row"]},
                ],
                agent="E",
            ))
            _log(run_dir, f"duplicate {a['txn_id']} ~ {b['txn_id']} (conf {confidence})")

    write_json(os.path.join(run_dir, "duplicates.json"),
               {"pairs": pairs, "count": len(pairs)})
    write_json(os.path.join(run_dir, "findings", "agent_e_duplicates.json"),
               [f.model_dump() for f in findings])
    _log(run_dir, f"emitted {len(findings)} duplicate findings")
    print(f"[Agent E] Done — {len(pairs)} duplicate pair(s).")
