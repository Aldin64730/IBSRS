"""
app.py — IBSRS Streamlit UI.

The final deliverable's front door:
  - upload a bank statement + GL export (or a full .zip recon bundle)
  - tune the Policy Pack live in the sidebar (tolerances/thresholds)
  - run the reconciliation pipeline programmatically
  - read the metrics banner, the rendered markdown deliverables, and download
    every artifact

No secrets in the UI: the OpenAI key is read from .env by the pipeline, never typed
here. Run with:  streamlit run app.py
"""

from __future__ import annotations

import os
import sys
import time
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

import streamlit as st
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))

from orchestration_scaffolding import run_pipeline  # noqa: E402

BASE_POLICY_PATH = os.path.join(ROOT, "config", "policy_pack.yaml")

ARTIFACTS = [
    ("context_packet.json", "json"),
    ("evidence_index.json", "json"),
    ("transactions.json", "json"),
    ("match_result.json", "json"),
    ("timing_diffs.csv", "csv"),
    ("duplicates.json", "json"),
    ("findings.json", "json"),
    ("journal_entries.json", "json"),
    ("metrics.json", "json"),
    ("recon_statement.md", "md"),
    ("exceptions.md", "md"),
    ("audit_log.md", "md"),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def load_base_policy() -> dict:
    with open(BASE_POLICY_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_artifact(run_dir: str, name: str) -> str | None:
    path = os.path.join(run_dir, name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_bundle_from_uploads(work_dir: str, bank_file, gl_file,
                              account_id: str, period: str, currency: str) -> str:
    """Write uploaded files + a synthesized manifest into work_dir; return its path."""
    bank_name = bank_file.name
    gl_name = gl_file.name
    with open(os.path.join(work_dir, bank_name), "wb") as f:
        f.write(bank_file.getbuffer())
    with open(os.path.join(work_dir, gl_name), "wb") as f:
        f.write(gl_file.getbuffer())

    bank_fmt = "pdf" if bank_name.lower().endswith(".pdf") else "csv"
    manifest = {
        "bundle_id": f"ui_{account_id}",
        "period": period,
        "account_id": account_id,
        "currency": currency,
        "files": {
            "bank_statement": {"filename": bank_name, "format": bank_fmt, "required": True},
            "gl_export": {"filename": gl_name, "format": "csv", "required": True},
        },
    }
    with open(os.path.join(work_dir, "manifest.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return work_dir


def extract_zip_bundle(work_dir: str, zip_file) -> str:
    """Extract an uploaded .zip and return the dir that contains manifest.yaml."""
    with zipfile.ZipFile(zip_file) as zf:
        zf.extractall(work_dir)
    for cur, _dirs, files in os.walk(work_dir):
        if "manifest.yaml" in files:
            return cur
    raise FileNotFoundError("No manifest.yaml found inside the uploaded zip.")


def write_temp_policy(work_dir: str, policy: dict) -> str:
    path = os.path.join(work_dir, "policy_pack.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(policy, f, sort_keys=False)
    return path


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="IBSRS — Bank Reconciliation", page_icon="🏦", layout="wide")
st.title("🏦 IBSRS — Intelligent Bank Reconciliation System")
st.caption("Deterministic multi-agent reconciliation. Decisions are code; prose is LLM.")

# ---- Sidebar: Policy Pack (live knobs) ------------------------------------ #
base_policy = load_base_policy()
m = base_policy.get("matching", {})
th = base_policy.get("thresholds", {})

st.sidebar.header("⚙️ Policy Pack")
st.sidebar.caption("Change a tolerance and re-run to see decisions move.")

fuzzy = st.sidebar.slider("Fuzzy description threshold", 0.50, 1.00,
                          float(m.get("fuzzy_description_threshold", 0.85)), 0.01)
amt_tol = st.sidebar.number_input("Amount tolerance (fraction)", 0.0, 0.20,
                                  float(m.get("amount_tolerance_pct", 0.01)), 0.005, format="%.3f")
timing_window = st.sidebar.number_input("Timing window (days)", 0, 60,
                                        int(m.get("timing_window_days", 5)))
high_value = st.sidebar.number_input("High-value escalation (USD)", 0.0, 1_000_000.0,
                                     float(th.get("high_value_escalation", 10000)), 500.0)
dup_var = st.sidebar.number_input("Duplicate amount variance", 0.0, 100.0,
                                  float(th.get("duplicate_amount_variance", 0.0)), 0.01, format="%.2f")
dup_window = st.sidebar.number_input("Duplicate date window (days)", 0, 30,
                                     int(th.get("duplicate_date_window_days", 3)))

st.sidebar.divider()
llm_pdf = st.sidebar.toggle(
    "LLM PDF extraction", value=False,
    help="When a PDF has no detectable table, let the LLM read it. Verified by "
         "the balance check; off = deterministic pdfplumber only.")
key_set = bool(os.environ.get("OPENAI_API_KEY")) or os.path.exists(os.path.join(ROOT, ".env"))
st.sidebar.caption(("🔑 OpenAI key detected (from .env)" if key_set
                    else "⚠️ No OpenAI key found — the run will fail without one."))


def current_policy() -> dict:
    policy = json.loads(json.dumps(base_policy))  # deep copy
    policy.setdefault("matching", {}).update({
        "fuzzy_description_threshold": fuzzy,
        "amount_tolerance_pct": amt_tol,
        "timing_window_days": int(timing_window),
    })
    policy.setdefault("thresholds", {}).update({
        "high_value_escalation": high_value,
        "duplicate_amount_variance": dup_var,
        "duplicate_date_window_days": int(dup_window),
    })
    policy.setdefault("llm", {})["use_for_pdf_extraction"] = bool(llm_pdf)
    return policy


# ---- Inputs --------------------------------------------------------------- #
st.subheader("1 · Inputs")
col1, col2 = st.columns(2)
with col1:
    bank_file = st.file_uploader("Bank statement (.csv / .pdf)", type=["csv", "pdf"])
    gl_file = st.file_uploader("GL export (.csv)", type=["csv"])
with col2:
    zip_file = st.file_uploader("…or a full recon bundle (.zip)", type=["zip"])
    acct = st.text_input("Account id", "ACC-UPLOAD")
    period = st.text_input("Period (YYYY-MM)", datetime.now().strftime("%Y-%m"))
    currency = st.text_input("Currency", "USD")

run_clicked = st.button("▶ Run reconciliation", type="primary", use_container_width=True)


# ---- Run ------------------------------------------------------------------ #
if run_clicked:
    if not zip_file and not (bank_file and gl_file):
        st.error("Provide a bank statement **and** a GL export, or upload a .zip bundle.")
        st.stop()

    work_dir = tempfile.mkdtemp(prefix="ibsrs_ui_")
    try:
        if zip_file:
            bundle_path = extract_zip_bundle(work_dir, zip_file)
        else:
            bundle_path = build_bundle_from_uploads(
                work_dir, bank_file, gl_file, acct, period, currency)

        policy_path = write_temp_policy(work_dir, current_policy())

        with st.spinner("Running A → B → C → D → E → H…"):
            t0 = time.time()
            run_dir_rel = run_pipeline(os.path.abspath(bundle_path),
                                       os.path.abspath(policy_path))
            elapsed = time.time() - t0

        st.session_state["run_dir"] = os.path.join(ROOT, run_dir_rel)
        st.session_state["elapsed"] = elapsed
        st.success(f"Reconciliation complete in {elapsed:.2f}s.")
    except Exception as exc:
        st.exception(exc)
        st.stop()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ---- Results -------------------------------------------------------------- #
run_dir = st.session_state.get("run_dir")
if run_dir and os.path.isdir(run_dir):
    st.divider()
    st.subheader("2 · Results")

    metrics_raw = read_artifact(run_dir, "metrics.json")
    metrics = json.loads(metrics_raw) if metrics_raw else {}

    c = st.columns(5)
    c[0].metric("Match rate", f"{metrics.get('match_rate', 0):.0%}")
    c[1].metric("Exceptions", metrics.get("exception_count", 0))
    c[2].metric("High severity", metrics.get("high_severity_count", 0))
    c[3].metric("Journal entries", metrics.get("journal_entry_count", 0))
    c[4].metric("Throughput", f"{metrics.get('bank_txn_count', 0)} txns "
                              f"/ {st.session_state.get('elapsed', 0):.2f}s")

    tabs = st.tabs(["📄 Recon statement", "⚠️ Exceptions", "🧾 Timing diffs",
                    "🔎 Findings", "📒 Journal entries", "🧭 Audit log", "⬇️ Downloads"])

    with tabs[0]:
        st.markdown(read_artifact(run_dir, "recon_statement.md") or "_not generated_")
    with tabs[1]:
        st.markdown(read_artifact(run_dir, "exceptions.md") or "_not generated_")
    with tabs[2]:
        csv_text = read_artifact(run_dir, "timing_diffs.csv")
        if csv_text and csv_text.strip():
            import csv as _csv
            import io
            rows = list(_csv.DictReader(io.StringIO(csv_text)))
            st.dataframe(rows, use_container_width=True) if rows else st.info("No timing differences.")
        else:
            st.info("No timing differences.")
    with tabs[3]:
        findings = json.loads(read_artifact(run_dir, "findings.json") or "[]")
        st.dataframe(findings, use_container_width=True) if findings else st.success("No exceptions — fully reconciled.")
    with tabs[4]:
        jes = json.loads(read_artifact(run_dir, "journal_entries.json") or "[]")
        if jes:
            for je in jes:
                st.markdown(f"**{je['je_id']}** ({je['date']}) — {je['memo']}")
                st.dataframe(je["lines"], use_container_width=True)
        else:
            st.info("No suggested journal entries.")
    with tabs[5]:
        st.markdown(read_artifact(run_dir, "audit_log.md") or "_not generated_")
    with tabs[6]:
        st.caption(f"Run directory: `{run_dir}`")
        for name, _kind in ARTIFACTS:
            data = read_artifact(run_dir, name)
            if data is not None:
                st.download_button(f"⬇️ {name}", data, file_name=name, key=f"dl_{name}")
else:
    st.info("Upload inputs and click **Run reconciliation** to see results.")
