"""
agent_h_orchestrator.py
Agent H — Exception Triage & Orchestration (the Judge).

Decisions are code; prose is LLM. H merges the C/D and E findings, dedupes and
prioritizes them (rules), computes journal-entry amounts and metrics in code,
and uses the LLM only to *narrate* the deterministic draft into the final prose.
Emits:
  findings.json, journal_entries.json, exceptions.md, recon_statement.md,
  audit_log.md, metrics.json
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

from file_utils import read_json, write_json, write_markdown, append_log
from schemas import Finding, JournalEntry, JournalLine
from config import Config
from llm import LLM


SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

# Agent H's narration system prompt. The Judge only rewrites the deterministic
# draft into prose — it must never alter the figures computed in code.
SYSTEM_PROMPT = """You are the reconciliation Judge for IBSRS, writing the human-readable narrative
of a completed bank reconciliation.

You will be given a DRAFT in Markdown that already contains every number,
finding, severity, and recommended action — all computed deterministically by
code. Your job is ONLY to rewrite the draft into clear, professional prose for a
controller or auditor to read.

HARD RULES:
- Never change, add, or remove a number, amount, finding id, severity, match
  rate, or recommended action. The figures in the draft are authoritative.
- Do not invent transactions, accounts, or conclusions not present in the draft.
- Preserve all finding ids (F-xxxx) and journal ids (JE-xxxx) exactly.
- Keep Markdown structure (headings, bullet lists). Improve wording and flow only.
- Be concise and audit-appropriate. No marketing tone, no speculation.

Return only the polished Markdown document.
"""


def _log(run_dir: str, msg: str) -> None:
    append_log(os.path.join(run_dir, "logs", "agent_h.log"), msg)


def _merge_findings(run_dir: str) -> list[dict]:
    parts = ["findings/agent_cd_variances.json", "findings/agent_e_duplicates.json"]
    merged: list[dict] = []
    for rel in parts:
        path = os.path.join(run_dir, rel)
        if os.path.exists(path):
            merged.extend(read_json(path))

    # Dedupe by (type, sorted txn_ids+gl_ids); prioritize by severity then amount.
    seen: dict[tuple, dict] = {}
    for f in merged:
        key = (f["type"], tuple(sorted(f.get("txn_ids", []) + f.get("gl_ids", []))))
        if key not in seen:
            seen[key] = f
    unified = list(seen.values())
    unified.sort(key=lambda f: (SEVERITY_RANK.get(f["severity"], 9), -f["confidence"]))

    # Re-number stably so findings.json IDs are contiguous and ordered.
    for i, f in enumerate(unified, start=1):
        f["finding_id"] = f"F-{i:04d}"
    return unified


def _journal_entries(run_dir: str, findings: list[dict], llm: LLM) -> list[dict]:
    txns = {t["txn_id"]: t for t in read_json(os.path.join(run_dir, "transactions.json"))}
    ctx = read_json(os.path.join(run_dir, "context_packet.json"))
    period_end = f"{ctx.get('period','')}-31" if len(str(ctx.get("period", ""))) == 7 else \
        ctx.get("period", "")

    entries: list[JournalEntry] = []
    je = 0

    def amt_of(txn_id: str) -> Decimal:
        return abs(Decimal(str(txns[txn_id]["amount"])))

    for f in findings:
        lines = None
        default_memo = None
        if f["type"].endswith("bank_charge"):
            value = amt_of(f["txn_ids"][0])
            lines = [
                JournalLine(account="6500-BankFees", debit=float(value), credit=0.0),
                JournalLine(account="1010-Cash", debit=0.0, credit=float(value)),
            ]
            default_memo = f"Record bank service charge of {value} not in GL ({f['finding_id']})."
        elif f["type"] == "duplicate_transaction":
            dup_txn = f["txn_ids"][-1]
            value = amt_of(dup_txn)
            lines = [
                JournalLine(account="1010-Cash", debit=float(value), credit=0.0),
                JournalLine(account="2000-AP", debit=0.0, credit=float(value)),
            ]
            default_memo = f"Reverse duplicate transaction {dup_txn} of {value} ({f['finding_id']})."

        if lines is None:
            continue

        je += 1
        memo = llm.complete(
            system="You write a one-sentence accounting journal memo. Return only the memo.",
            user=json.dumps({"default_memo": default_memo, "finding": f}),
            purpose="memo",
        ).splitlines()[-1].strip() or default_memo
        entries.append(JournalEntry(
            je_id=f"JE-{je:04d}", date=period_end, lines=lines,
            memo=memo, source_finding=f["finding_id"], status="suggested",
        ))
        _log(run_dir, f"{entries[-1].je_id} from {f['finding_id']}: {memo}")

    return [e.model_dump() for e in entries]


def _draft_recon_statement(ctx, match, findings, jes) -> str:
    s = match["summary"]
    lines = [
        f"# Bank Reconciliation Statement — {ctx['account'].get('id','')} — {ctx.get('period','')}",
        "",
        f"- Bank transactions: **{s.get('bank_txn_count',0)}**",
        f"- GL entries: **{s.get('gl_entry_count',0)}**",
        f"- Matched: **{s.get('matched_count',0)}**  |  Match rate: **{s.get('match_rate',0):.0%}**",
        f"- Open exceptions: **{len(findings)}**  |  Suggested journal entries: **{len(jes)}**",
        "",
        "## Exceptions",
    ]
    if not findings:
        lines.append("None — account fully reconciled.")
    for f in findings:
        lines.append(f"- **[{f['severity'].upper()}]** {f['type']}: {f['summary']} "
                     f"_(action: {f['recommended_action']})_")
    lines += ["", "## Suggested adjusting entries"]
    if not jes:
        lines.append("None.")
    for e in jes:
        lines.append(f"- {e['je_id']} ({e['date']}): {e['memo']}")
    return "\n".join(lines)


def _draft_exceptions(findings) -> str:
    lines = ["# Exceptions & Next Actions", ""]
    if not findings:
        return "# Exceptions & Next Actions\n\nNo open exceptions.\n"
    for f in findings:
        ev = ", ".join(str(e) for e in f.get("evidence", []))
        lines += [
            f"## {f['finding_id']} — {f['type']} [{f['severity'].upper()}]",
            f"- Summary: {f['summary']}",
            f"- Recommended action: **{f['recommended_action']}**",
            f"- Confidence: {f['confidence']}",
            f"- Evidence: {ev}",
        ]
        if f.get("open_questions"):
            lines.append(f"- Open questions: {'; '.join(f['open_questions'])}")
        lines.append("")
    return "\n".join(lines)


def _draft_audit_log(run_dir: str, ctx, match, findings, jes) -> str:
    pol = ctx.get("policy_snapshot", {})
    lines = [
        "# Audit Log",
        "",
        "## Policy in force",
        "```yaml",
        json.dumps(pol, indent=2),
        "```",
        "",
        "## Pipeline trace",
        f"- Agent A: built context packet; risk flags = {ctx.get('risk_flags', [])}",
        f"- Agent B: extracted {match['summary'].get('bank_txn_count',0)} transactions",
        f"- Agent C: match rate {match['summary'].get('match_rate',0):.0%}; "
        f"{len(match['unmatched_bank'])} unmatched bank, {len(match['unmatched_gl'])} unmatched GL",
        f"- Agent D/E: {len(findings)} unified findings after dedupe/prioritize",
        f"- Agent H: {len(jes)} journal entries computed in code",
        "",
        "## Findings → evidence",
    ]
    for f in findings:
        lines.append(f"- {f['finding_id']} ({f['type']}): evidence={f.get('evidence', [])}")
    return "\n".join(lines)


def _narrate(llm: LLM, draft: str, purpose: str) -> str:
    """LLM polishes the deterministic draft into the final narration."""
    return llm.complete(system=SYSTEM_PROMPT, user=draft, purpose=purpose)


def run(run_dir: str, policy: dict) -> None:
    print("[Agent H] Starting — triage & orchestration...")
    _log(run_dir, "=== Agent H: Triage & Orchestration ===")

    llm = LLM(Config())

    ctx = read_json(os.path.join(run_dir, "context_packet.json"))
    match = read_json(os.path.join(run_dir, "match_result.json"))

    findings = _merge_findings(run_dir)
    write_json(os.path.join(run_dir, "findings.json"), findings)
    _log(run_dir, f"unified findings: {len(findings)}")

    jes = _journal_entries(run_dir, findings, llm)
    write_json(os.path.join(run_dir, "journal_entries.json"), jes)

    # --- narration (LLM, with deterministic drafts as fallback) ----------
    recon_draft = _draft_recon_statement(ctx, match, findings, jes)
    exc_draft = _draft_exceptions(findings)
    audit_draft = _draft_audit_log(run_dir, ctx, match, findings, jes)

    write_markdown(os.path.join(run_dir, "recon_statement.md"),
                   _narrate(llm, recon_draft, "recon_statement"))
    write_markdown(os.path.join(run_dir, "exceptions.md"),
                   _narrate(llm, exc_draft, "exceptions"))
    write_markdown(os.path.join(run_dir, "audit_log.md"), audit_draft)  # audit stays code-exact

    # --- metrics (code) --------------------------------------------------
    metrics = {
        "bank_txn_count": match["summary"].get("bank_txn_count", 0),
        "gl_entry_count": match["summary"].get("gl_entry_count", 0),
        "matched_count": match["summary"].get("matched_count", 0),
        "match_rate": match["summary"].get("match_rate", 0.0),
        "exception_count": len(findings),
        "high_severity_count": sum(1 for f in findings if f["severity"] == "high"),
        "journal_entry_count": len(jes),
        "unmatched_bank": len(match["unmatched_bank"]),
        "unmatched_gl": len(match["unmatched_gl"]),
    }
    write_json(os.path.join(run_dir, "metrics.json"), metrics)
    _log(run_dir, f"metrics={metrics}")
    print(f"[Agent H] Done — {len(findings)} findings, {len(jes)} journal entries.")
