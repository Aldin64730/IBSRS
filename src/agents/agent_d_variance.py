"""
agent_d_variance.py
Agent D — Variance & Timing classification.

Pure rule-based. Categorizes every unmatched item (bank side and GL side) into:
  outstanding_check | deposit_in_transit | bank_charge | timing_difference
applies the materiality threshold (controller escalation), and emits:
  - timing_diffs.csv
  - findings/agent_cd_variances.json
"""

from __future__ import annotations

import os
from decimal import Decimal

from file_utils import read_json, read_csv_rows, write_json, write_csv, append_log
from schemas import Finding


CHARGE_KEYWORDS = ("charge", "fee", "service", "interest")
CHECK_KEYWORDS = ("check", "chk", "cheque")


def _log(run_dir: str, msg: str) -> None:
    append_log(os.path.join(run_dir, "logs", "agent_d.log"), msg)


def _classify_bank(desc: str, amount: Decimal) -> str:
    d = desc.lower()
    if any(k in d for k in CHARGE_KEYWORDS) and amount < 0:
        return "bank_charge"
    if amount > 0:
        return "deposit_in_transit"
    if any(k in d for k in CHECK_KEYWORDS):
        return "outstanding_check"
    return "timing_difference"


def _classify_gl(desc: str, amount: Decimal) -> str:
    d = desc.lower()
    if any(k in d for k in CHECK_KEYWORDS) and amount < 0:
        return "outstanding_check"
    if amount > 0:
        return "deposit_in_transit"
    return "timing_difference"


def run(run_dir: str, policy: dict) -> None:
    print("[Agent D] Starting — variance & timing...")
    _log(run_dir, "=== Agent D: Variance & Timing ===")

    high_value = Decimal(str(policy.get("thresholds", {}).get("high_value_escalation", 10000)))

    txns = {t["txn_id"]: t for t in read_json(os.path.join(run_dir, "transactions.json"))}
    match = read_json(os.path.join(run_dir, "match_result.json"))
    ctx = read_json(os.path.join(run_dir, "context_packet.json"))
    gl = {g["gl_id"]: g for g in read_csv_rows(ctx["inputs"]["gl_export"]["path"])}

    findings: list[Finding] = []
    timing_rows: list[dict] = []
    fid = 0

    def next_id() -> str:
        nonlocal fid
        fid += 1
        return f"F-{fid:04d}"

    # --- unmatched bank items --------------------------------------------
    for txn_id in match["unmatched_bank"]:
        t = txns[txn_id]
        amount = Decimal(str(t["amount"]))
        category = _classify_bank(t.get("description", ""), amount)
        severity = "high" if abs(amount) >= high_value else \
            ("medium" if category == "bank_charge" else "low")
        action = "create_journal_entry" if category == "bank_charge" else "review"
        if abs(amount) >= high_value:
            action = "controller_escalation"

        findings.append(Finding(
            finding_id=next_id(),
            type=f"unmatched_bank_{category}",
            severity=severity,
            confidence=0.9,
            txn_ids=[txn_id],
            summary=f"Bank item '{t.get('description','')}' ({amount}) classified as "
                    f"{category}; not present in GL.",
            recommended_action=action,
            evidence=[{"file": t["source"]["file"], "row": t["source"]["row"]}],
            agent="D",
            open_questions=([f"Amount {abs(amount)} exceeds materiality {high_value}"]
                            if abs(amount) >= high_value else []),
        ))
        timing_rows.append({
            "id": findings[-1].finding_id, "side": "bank", "ref_id": txn_id,
            "category": category, "date": t["date"], "amount": f"{amount:.2f}",
            "description": t.get("description", ""), "severity": severity,
        })
        _log(run_dir, f"{txn_id}: {category} severity={severity} action={action}")

    # --- unmatched GL items ----------------------------------------------
    for gl_id in match["unmatched_gl"]:
        g = gl[gl_id]
        amount = Decimal(str(g["amount"]))
        category = _classify_gl(g.get("description", ""), amount)
        severity = "high" if abs(amount) >= high_value else "low"
        findings.append(Finding(
            finding_id=next_id(),
            type=f"unmatched_gl_{category}",
            severity=severity,
            confidence=0.9,
            gl_ids=[gl_id],
            summary=f"GL entry '{g.get('description','')}' ({amount}) classified as "
                    f"{category}; not seen on bank statement this period.",
            recommended_action="carry_forward" if category == "outstanding_check" else "review",
            evidence=[{"file": os.path.basename(ctx['inputs']['gl_export']['path']),
                       "gl_id": gl_id}],
            agent="D",
        ))
        timing_rows.append({
            "id": findings[-1].finding_id, "side": "gl", "ref_id": gl_id,
            "category": category, "date": g["date"], "amount": f"{amount:.2f}",
            "description": g.get("description", ""), "severity": severity,
        })
        _log(run_dir, f"{gl_id}: {category} severity={severity}")

    write_csv(
        os.path.join(run_dir, "timing_diffs.csv"),
        timing_rows,
        fieldnames=["id", "side", "ref_id", "category", "date", "amount",
                    "description", "severity"],
    )
    write_json(
        os.path.join(run_dir, "findings", "agent_cd_variances.json"),
        [f.model_dump() for f in findings],
    )
    _log(run_dir, f"emitted {len(findings)} variance findings")
    print(f"[Agent D] Done — {len(findings)} findings.")
