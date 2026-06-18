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

import json
import os
from decimal import Decimal, ROUND_HALF_UP

from config import Config
from file_utils import read_json, read_csv_rows, write_json, append_log
from schemas import Transaction, Source


CENTS = Decimal("0.01")

# Instruction for the LLM rescue path (born-digital but un-tabular PDFs).
_LLM_EXTRACT_SYSTEM = (
    "You extract transactions from a bank statement page. "
    "Return ONLY a JSON array (no prose, no code fences). Each element has keys: "
    "date (YYYY-MM-DD), value_date (YYYY-MM-DD or null), description (string), "
    "reference (string or null), amount (signed number; negative = money out, "
    "positive = money in; no thousands separators or currency symbols), and "
    "balance (running balance after the transaction as a number, or null). "
    "Preserve the order the rows appear on the page. Do not invent, drop, or "
    "merge rows; if a field is absent use null. Output strictly valid JSON."
)


def _log(run_dir: str, msg: str) -> None:
    append_log(os.path.join(run_dir, "logs", "agent_b.log"), msg)


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def _normalize_rows(rows, filename, *, method: str = "structured") -> list[Transaction]:
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
        if method == "llm":
            flags.append("llm_extracted")
            confidence = min(confidence, 0.8)

        txns.append(
            Transaction(
                txn_id=f"BNK-{i + 1:04d}",
                date=str(row["date"]).strip(),
                value_date=str(row.get("value_date") or row["date"]).strip(),
                amount=float(amount),
                direction="debit" if amount < 0 else "credit",
                description=desc,
                reference=ref,
                balance_after=float(_money(balance)) if balance else None,
                # CSV/table rows carry a source row (+2: header + 1-index); LLM
                # rows can't be tied to one source row, so record the page.
                source=Source(
                    file=filename,
                    row=(None if method == "llm" else i + 2),
                    page=(1 if method == "llm" else None),
                ),
                confidence=confidence,
                flags=flags,
            )
        )
    return txns


def _parse_csv(path: str) -> list[Transaction]:
    return _normalize_rows(read_csv_rows(path), os.path.basename(path))


def _parse_pdf(path: str) -> list[Transaction]:
    """Pass 1 for PDFs: born-digital ruled tables via pdfplumber.

    Deterministic and free. Returns [] when the page has no detectable table
    (messy layout / scanned) — the caller then decides whether to try the LLM
    rescue (see _llm_rescue) before falling back to synthetic.
    """
    try:
        import pdfplumber
    except Exception:
        return []
    rows = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                header = [(c or "").strip().lower() for c in table[0]]
                for r in table[1:]:
                    rows.append(dict(zip(header, [(c or "").strip() for c in r])))
    return _normalize_rows(rows, os.path.basename(path)) if rows else []


def _pdf_page_text(path: str) -> str:
    """Raw text of every page (works even when table detection fails)."""
    try:
        import pdfplumber
    except Exception:
        return ""
    parts = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def _clean_num(value) -> str:
    """Normalize a model-supplied number: strip separators, ( ) => negative."""
    s = str(value).strip().replace(",", "").replace("$", "").replace(" ", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return s


def _parse_llm_json(text: str) -> list[dict]:
    """Best-effort: pull the JSON array out of the model's reply."""
    s = text.strip()
    if s.startswith("```"):                      # tolerate ```json fences
        s = s.strip("`")
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1:]
    if "[" in s and "]" in s:                    # slice to the outermost array
        s = s[s.index("["):s.rindex("]") + 1]
    try:
        data = json.loads(s)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("transactions") or data.get("rows") or []
    return data if isinstance(data, list) else []


def _llm_rescue(path: str, config: Config, run_dir: str) -> list[Transaction]:
    """Pass 2 for PDFs: let the LLM structure the raw page text into rows.

    Verified downstream by the balance check — the caller only adopts these rows
    when they reconcile (or when pdfplumber produced nothing at all).
    """
    text = _pdf_page_text(path)
    if not text:
        _log(run_dir, "llm_rescue: no extractable text (scanned PDF?) — skipping")
        return []
    from llm import LLM
    try:
        out = LLM(config).complete(
            system=_LLM_EXTRACT_SYSTEM, user=text, purpose="pdf_extraction")
    except Exception as exc:
        _log(run_dir, f"llm_rescue: LLM call failed — {exc}")
        return []

    rows = []
    for r in _parse_llm_json(out):
        if not isinstance(r, dict) or r.get("date") in (None, "") \
                or r.get("amount") in (None, ""):
            continue
        rows.append({
            "date": str(r.get("date")).strip(),
            "value_date": (str(r["value_date"]).strip()
                           if r.get("value_date") else None),
            "description": str(r.get("description") or "").strip(),
            "reference": (str(r["reference"]).strip()
                          if r.get("reference") else None),
            "amount": _clean_num(r.get("amount")),
            "balance": (_clean_num(r["balance"])
                        if r.get("balance") not in (None, "") else None),
        })
    _log(run_dir, f"llm_rescue: model returned {len(rows)} usable rows")
    return _normalize_rows(rows, os.path.basename(path), method="llm")


def _reconciles(txns: list[Transaction]) -> bool:
    """Pure check (no mutation): does the running balance tie out row by row?"""
    with_balance = [t for t in txns if t.balance_after is not None]
    if not with_balance:
        return False
    running = _money(with_balance[0].balance_after) - _money(with_balance[0].amount)
    for t in with_balance:
        running += _money(t.amount)
        if running != _money(t.balance_after):
            return False
    return True


def _llm_extraction_enabled(policy: dict) -> bool:
    """Off by default. Enable via IBSRS_LLM_PDF_EXTRACTION or policy llm.*."""
    if os.environ.get("IBSRS_LLM_PDF_EXTRACTION", "").strip().lower() in (
            "1", "true", "yes", "on"):
        return True
    return bool((policy.get("llm") or {}).get("use_for_pdf_extraction", False))


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
        # Tier 2: LLM rescue when pdfplumber found nothing, or found rows that
        # don't reconcile. Adopt the rescued rows only if they reconcile (or if
        # pdfplumber produced nothing), so the balance check stays the arbiter.
        if _llm_extraction_enabled(policy) and (not txns or not _reconciles(txns)):
            _log(run_dir, "pdf table parse weak — attempting LLM rescue")
            rescued = _llm_rescue(path, Config(), run_dir)
            if rescued and (_reconciles(rescued) or not txns):
                _log(run_dir, f"adopting LLM-rescued extraction ({len(rescued)} txns)")
                txns = rescued
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
