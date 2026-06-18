"""
schemas.py
Pydantic v2 contracts for every IBSRS artifact. These are the single source of
truth for artifact shape. Agents validate on write (fail loud) and the JSON
Schema for each model is exported to schemas/*.json for documentation.

Money note: amounts are carried as floats in the serialized artifacts (so the
JSON stays human-readable and diffable), but all *arithmetic* in the agents is
done with decimal.Decimal and only quantized to 2dp floats at the edge.
"""

from __future__ import annotations

from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #
class Source(BaseModel):
    file: str
    row: Optional[int] = None
    page: Optional[int] = None
    bbox: Optional[List[float]] = None


# --------------------------------------------------------------------------- #
# Agent A — context packet
# --------------------------------------------------------------------------- #
class ContextPacket(BaseModel):
    bundle_id: str
    period: str
    account: Dict[str, Any]
    inputs: Dict[str, Any]                      # resolved file paths for later agents
    gl_mapping: Dict[str, Any] = Field(default_factory=dict)
    prior_period: Dict[str, Any] = Field(default_factory=dict)
    fee_schedule: Dict[str, Any] = Field(default_factory=dict)
    fx_rates: Dict[str, Any] = Field(default_factory=dict)
    risk_flags: List[str] = Field(default_factory=list)
    policy_snapshot: Dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Agent B — normalized transaction
# --------------------------------------------------------------------------- #
class Transaction(BaseModel):
    txn_id: str
    date: str
    value_date: Optional[str] = None
    amount: float
    currency: str = "USD"
    direction: Literal["debit", "credit"]
    description: str = ""
    reference: Optional[str] = None
    balance_after: Optional[float] = None
    source: Source
    confidence: float = 1.0
    flags: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Agent C — match result
# --------------------------------------------------------------------------- #
class MatchPair(BaseModel):
    bank_txn: str
    gl_entries: List[str]
    match_type: Literal["1:1", "1:M", "M:1"]
    method: Literal["reference", "amount_date", "fuzzy_description"]
    confidence: float


class MatchResult(BaseModel):
    matched: List[MatchPair] = Field(default_factory=list)
    unmatched_bank: List[str] = Field(default_factory=list)
    unmatched_gl: List[str] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Agents D / E / H — unified finding
# --------------------------------------------------------------------------- #
class Finding(BaseModel):
    finding_id: str
    type: str
    severity: Literal["low", "medium", "high"]
    confidence: float
    txn_ids: List[str] = Field(default_factory=list)
    gl_ids: List[str] = Field(default_factory=list)
    summary: str
    recommended_action: str
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    agent: str
    open_questions: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Agent H — journal entries
# --------------------------------------------------------------------------- #
class JournalLine(BaseModel):
    account: str
    debit: float = 0.0
    credit: float = 0.0


class JournalEntry(BaseModel):
    je_id: str
    date: str
    lines: List[JournalLine]
    memo: str
    source_finding: Optional[str] = None
    status: Literal["suggested", "approved", "posted"] = "suggested"


# --------------------------------------------------------------------------- #
# JSON Schema export
# --------------------------------------------------------------------------- #
# Maps the schemas/*.json filenames to the model whose schema they hold.
SCHEMA_EXPORTS = {
    "context_schema.json": ContextPacket,
    "transactions_schema.json": Transaction,
    "match_result_schema.json": MatchResult,
    "findings_schema.json": Finding,
}


def export_json_schemas(out_dir: str) -> None:
    """Write each model's JSON Schema to out_dir/<name>.json."""
    import json
    import os

    os.makedirs(out_dir, exist_ok=True)
    for filename, model in SCHEMA_EXPORTS.items():
        schema = model.model_json_schema()
        with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
            f.write("\n")


if __name__ == "__main__":
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.abspath(os.path.join(here, "..", "..", "schemas"))
    export_json_schemas(target)
    print(f"Exported JSON schemas to {target}")
