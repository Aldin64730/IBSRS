"""
agent_a_gatekeeper.py
Agent A — Statement Intake & Context Packet Construction (the Gatekeeper).

No LLM. Deterministic: read the manifest, validate required files exist and are
non-empty (corrupt-file / empty-file filter), aggregate account metadata, prior
period, fee schedule and FX, raise risk flags, and write:
  - context_packet.json   (account meta + resolved input paths for later agents)
  - evidence_index.json   (file-level provenance: path + sha256 + row count)
"""

from __future__ import annotations

import os
import re

from file_utils import read_yaml, read_json, read_text, write_json, append_log, sha256_file
from schemas import ContextPacket


def _log(run_dir: str, msg: str) -> None:
    append_log(os.path.join(run_dir, "logs", "agent_a.log"), msg)


def _parse_prior_closing(md_text: str) -> dict:
    """Pull the closing balances out of the prior reconciliation markdown."""
    out = {}
    m = re.search(r"Closing book balance.*?([\d,]+\.\d{2})", md_text, re.IGNORECASE)
    if m:
        out["closing_book_balance"] = float(m.group(1).replace(",", ""))
    m = re.search(r"Closing bank balance.*?([\d,]+\.\d{2})", md_text, re.IGNORECASE)
    if m:
        out["closing_bank_balance"] = float(m.group(1).replace(",", ""))
    return out


def run(bundle_path: str, run_dir: str, policy: dict) -> None:
    print("[Agent A] Starting — intake & context...")
    _log(run_dir, "=== Agent A: Intake & Context ===")
    _log(run_dir, f"bundle_path={bundle_path}")

    manifest = read_yaml(os.path.join(bundle_path, "manifest.yaml"))
    files = manifest.get("files", {})

    inputs: dict = {"bundle_path": os.path.abspath(bundle_path)}
    evidence_index: dict = {"files": {}}
    risk_flags: list[str] = []

    for role, spec in files.items():
        filename = spec.get("filename")
        required = spec.get("required", False)
        fmt = spec.get("format")
        path = os.path.join(bundle_path, filename) if filename else None
        present = bool(path) and os.path.exists(path) and os.path.getsize(path) > 0

        if not present:
            if required:
                raise FileNotFoundError(
                    f"Agent A: required file '{role}' ({filename}) is missing or empty."
                )
            _log(run_dir, f"optional file '{role}' absent/empty — skipped")
            inputs[role] = None
            continue

        inputs[role] = {"path": os.path.abspath(path), "format": fmt}
        evidence_index["files"][role] = {
            "path": os.path.abspath(path),
            "filename": filename,
            "format": fmt,
            "sha256": sha256_file(path),
            "bytes": os.path.getsize(path),
        }
        _log(run_dir, f"registered '{role}' -> {filename} ({fmt})")

    # --- prior period -----------------------------------------------------
    prior_period: dict = {}
    if inputs.get("prior_recon"):
        prior_period = _parse_prior_closing(read_text(inputs["prior_recon"]["path"]))
        _log(run_dir, f"prior_period={prior_period}")

    # --- fee schedule -----------------------------------------------------
    fee_schedule: dict = {}
    if inputs.get("bank_fee_schedule"):
        fee_schedule = {"source": inputs["bank_fee_schedule"]["path"]}

    # --- fx ---------------------------------------------------------------
    fx_rates: dict = {}
    if inputs.get("fx_rates"):
        fx_rates = read_json(inputs["fx_rates"]["path"])
        non_base = [c for c in fx_rates.get("rates", {}) if c != fx_rates.get("base")]
        if non_base:
            risk_flags.append("fx_exposure")

    # --- account / risk ---------------------------------------------------
    account = {
        "id": manifest.get("account_id"),
        "currency": manifest.get("currency", "USD"),
        "type": manifest.get("account_type", "operating_checking"),
    }
    high_value = policy.get("thresholds", {}).get("high_value_escalation", 10000)
    risk_flags.append(f"materiality_threshold={high_value}")

    packet = ContextPacket(
        bundle_id=manifest.get("bundle_id", "unknown_bundle"),
        period=str(manifest.get("period", "")),
        account=account,
        inputs=inputs,
        gl_mapping={"cash_account": "1010-Cash"},
        prior_period=prior_period,
        fee_schedule=fee_schedule,
        fx_rates=fx_rates,
        risk_flags=risk_flags,
        policy_snapshot=policy,
    )

    write_json(os.path.join(run_dir, "context_packet.json"), packet.model_dump())
    write_json(os.path.join(run_dir, "evidence_index.json"), evidence_index)
    _log(run_dir, f"risk_flags={risk_flags}")
    print("[Agent A] Done.")
