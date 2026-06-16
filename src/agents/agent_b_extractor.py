"""
agent_b_extractor.py
Agent B — Transaction Extraction.

Core logic (deterministic): parse the bank statement into normalized
transactions and assert the running balance closes. CSV is parsed directly;
born-digital PDF is parsed with pdfplumber when available. If nothing usable can
be extracted, a small deterministic synthetic statement is generated so the
pipeline still demos end-to-end. (LLM fallback for messy PDF rows is a
documented extension point — see _parse_pdf.)
"""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP

from file_utils import read_json, read_csv_rows, write_json, append_log
from schemas import Transaction, Source


CENTS = Decimal("0.01")


def _log(run_dir: str, msg: str) -> None:
    append_log(os.path.join(run_dir, "logs", "agent_b.log"), msg)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def _normalize_rows(rows, filename) -> list[Transaction]:
    txns: list[Transaction] = []
    for i, row in enumerate(rows):
        amount = _money(row["amount"])
        ref = (row.get("reference") or "").strip() or None
        balance = row.get("balance")
        flags: list[str] = []
        confidence = 1.0
        if ref is None:
            flags.append("missing_reference")
            confidence = 0.85
        desc = (row.get("description") or "").strip()
        if len(desc) < 4:
            flags.append("truncated_description")
            confidence = min(confidence, 0.7)

        txns.append(
            Transaction(
                txn_id=f"BNK-{i + 1:04d}",
                date=row["date"].strip(),
                value_date=(row.get("value_date") or row["date"]).strip(),
                amount=float(amount),
                direction="debit" if amount < 0 else "credit",
                description=desc,
                reference=ref,
                balance_after=float(_money(balance)) if balance else None,
                source=Source(file=filename, row=i + 2),  # +2: header + 1-index
                confidence=confidence,
                flags=flags,
            )
        )
    return txns


def _parse_csv(path: str) -> list[Transaction]:
    return _normalize_rows(read_csv_rows(path), os.path.basename(path))


def _parse_pdf(path: str) -> list[Transaction]:
    """Born-digital PDF via pdfplumber. LLM rescue for messy rows goes here."""
    try:
        import pdfplumber  # noqa: F401
    except Exception:
        return []
    rows = []
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                header = [c.strip().lower() for c in table[0]]
                for r in table[1:]:
                    rows.append(dict(zip(header, [c.strip() for c in r])))
    return _normalize_rows(rows, os.path.basename(path)) if rows else []


def _synthetic(filename: str) -> list[Transaction]:
    """Deterministic synthetic fallback so the pipeline never dead-ends."""
    samples = [
        ("2026-05-03", "ACH PAYMENT VENDOR X", "REF00001", "-1000.00", "49000.00"),
        ("2026-05-12", "DEPOSIT CUSTOMER A", "DEP00002", "2000.00", "51000.00"),
    ]
    rows = [
        {"date": d, "value_date": d, "description": desc, "reference": ref,
         "amount": amt, "balance": bal}
        for d, desc, ref, amt, bal in samples
    ]
    txns = _normalize_rows(rows, filename)
    for t in txns:
        t.flags.append("synthetic")
        t.confidence = 0.5
    return txns


def _balance_check(run_dir: str, txns: list[Transaction]) -> None:
    """Opening + Σ(amounts) == closing; running balance must agree row by row."""
    with_balance = [t for t in txns if t.balance_after is not None]
    if not with_balance:
        _log(run_dir, "balance_check=skipped (no balances in source)")
        return
    opening = _money(with_balance[0].balance_after) - _money(with_balance[0].amount)
    running = opening
    ok = True
    for t in with_balance:
        running += _money(t.amount)
        if running != _money(t.balance_after):
            ok = False
            t.flags.append("balance_mismatch")
            _log(run_dir, f"balance mismatch at {t.txn_id}: "
                          f"expected {running}, stated {t.balance_after}")
    closing = _money(with_balance[-1].balance_after)
    _log(run_dir, f"balance_check opening={opening} closing={closing} ok={ok}")


def run(run_dir: str, policy: dict) -> None:
    print("[Agent B] Starting — transaction extraction...")
    _log(run_dir, "=== Agent B: Transaction Extraction ===")

    ctx = read_json(os.path.join(run_dir, "context_packet.json"))
    bank = ctx["inputs"].get("bank_statement")
    if not bank:
        raise RuntimeError("Agent B: no bank_statement in context packet.")

    path, fmt = bank["path"], bank["format"]
    _log(run_dir, f"parsing {os.path.basename(path)} as {fmt}")

    if fmt == "csv":
        txns = _parse_csv(path)
    elif fmt == "pdf":
        txns = _parse_pdf(path)
    else:
        txns = []

    if not txns:
        _log(run_dir, "extraction yielded nothing usable — synthetic fallback")
        txns = _synthetic(os.path.basename(path))

    _balance_check(run_dir, txns)

    write_json(
        os.path.join(run_dir, "transactions.json"),
        [t.model_dump() for t in txns],
    )
    _log(run_dir, f"extracted {len(txns)} transactions")
    print(f"[Agent B] Done — {len(txns)} transactions.")
