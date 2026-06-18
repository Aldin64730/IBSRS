# IBSRS — Intelligent Bank Reconciliation System

A multi-agent, **file-based, deterministic** bank reconciliation pipeline. It takes a
bank statement and a GL export, normalizes transactions, matches them, categorizes
timing differences, detects duplicates, triages exceptions, and produces an
ERP-ready, fully auditable set of artifacts.

> Design principle: **decisions are code, prose is LLM.** Every number and match
> decision is made by deterministic Python; OpenAI narrates the human-readable
> documents (Agent H) and — off by default — rescues un-tabular PDFs into rows
> (Agent B). See [`context.md`](context.md) for the full spec.

## Quick start

```bash
pip install -r requirements.txt          # pyyaml, pydantic, openai, python-dotenv (others optional)
# ensure OPENAI_API_KEY is set in .env (already present)

streamlit run app.py                     # the UI (recommended)

python run.py                            # …or headless: default sample bundle
python run.py inputs/recon_bundle_001    # …or an explicit bundle
```

Outputs land in `runs/run_<bundle_id>__<UTC-timestamp>/`.

### UI (`app.py`)

Upload a bank statement + GL export (or a full `.zip` recon bundle), tune the Policy
Pack live in the sidebar (tolerances/thresholds — changing one visibly moves the
decisions), and click **Run reconciliation**. You get a metrics banner plus tabs for
the recon statement, exceptions, timing diffs, findings, journal entries, audit log,
and a download for every artifact. The OpenAI key is read from `.env` and never
typed into the UI.

### Determinism

LLM calls are `temperature=0` and cached by an input hash under `.cache/llm/`, so
re-running a bundle produces **byte-identical** artifacts.

## Pipeline

```
run.py → orchestration_scaffolding.run_pipeline
  Agent A (gatekeeper)   → context_packet.json, evidence_index.json
  Agent B (extractor)    → transactions.json            (+ balance assertion; LLM PDF rescue)
  Agent C (gl_matcher)   → match_result.json            (reference → amount/date → fuzzy)
  Agent D (variance)     → timing_diffs.csv, findings/agent_cd_variances.json
  Agent E (duplicates)   → duplicates.json, findings/agent_e_duplicates.json
  Agent H (orchestrator) → findings.json, journal_entries.json, exceptions.md,
                           recon_statement.md, audit_log.md, metrics.json
```

## Layout

| Path | Purpose |
|---|---|
| `src/core/` | `schemas.py` (pydantic contracts), `config.py`, `llm.py`, `file_utils.py`, `orchestration_scaffolding.py` |
| `src/agents/` | the six agents (A, B, C, D, E, H) |
| `src/prompts/` | per-agent system prompts (only H's is on the decision-free narration path) |
| `schemas/` | exported JSON Schema (regenerate: `python src/core/schemas.py`) |
| `config/policy_pack.yaml` | the Policy Pack — tolerances/thresholds, change without touching code |
| `inputs/recon_bundle_001/` | sample bundle (`manifest.yaml` + statement/GL/FX/prior) |
| `runs/` | generated artifacts (gitignored) |

## Sample bundle scenarios

The bundled `recon_bundle_001` is engineered to exercise: clean reference matches, a
bank service charge not in the GL (→ journal entry), a duplicate ACH (→ reversal), a
prior-month outstanding check (→ carry-forward), and a high-value unmatched deposit
(→ controller escalation).

## Status / next steps

Core pipeline (Commits 1–6 of `context.md`) and the Streamlit UI (Commit 7) are
implemented and runnable. Remaining: the `pytest` suite over multiple sample bundles,
and the stretch SOX / FX-revaluation agents.
