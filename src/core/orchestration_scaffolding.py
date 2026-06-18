"""
orchestration_scaffolding.py
Runs the 6-agent pipeline in sequence. Each agent reads from and writes to the
shared run directory, so any run can be replayed and inspected.

  A → context_packet.json, evidence_index.json
  B → transactions.json
  C → match_result.json
  D → timing_diffs.csv, findings/agent_cd_variances.json
  E → duplicates.json, findings/agent_e_duplicates.json
  H → findings.json, journal_entries.json, exceptions.md, recon_statement.md,
      audit_log.md, metrics.json
"""

import os
import sys
from datetime import datetime, timezone

# --- make src/core and src/agents importable, and run from repo root --------
_CORE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_CORE, "..", ".."))
for _p in (_CORE, os.path.join(_ROOT, "src", "agents")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from file_utils import read_yaml  # noqa: E402
from agent_a_gatekeeper import run as run_agent_a  # noqa: E402
from agent_b_extractor import run as run_agent_b  # noqa: E402
from agent_c_gl_matcher import run as run_agent_c  # noqa: E402
from agent_d_variance import run as run_agent_d  # noqa: E402
from agent_e_duplicates import run as run_agent_e  # noqa: E402
from agent_h_orchestrator import run as run_agent_h  # noqa: E402


def run_pipeline(bundle_path: str, policy_path: str = "config/policy_pack.yaml") -> str:
    os.chdir(_ROOT)  # relative paths (config/, runs/, inputs/) resolve from repo root

    manifest = read_yaml(os.path.join(bundle_path, "manifest.yaml"))
    bundle_id = manifest.get("bundle_id", "bundle")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{bundle_id}__{stamp}"
    run_dir = os.path.join("runs", run_id)
    os.makedirs(os.path.join(run_dir, "findings"), exist_ok=True)
    os.makedirs(os.path.join(run_dir, "logs"), exist_ok=True)

    print(f"\n{'=' * 56}")
    print(f"IBSRS Pipeline Starting — {run_id}")
    print(f"Bundle: {bundle_path}")
    print(f"{'=' * 56}\n")

    policy = read_yaml(policy_path)

    run_agent_a(bundle_path, run_dir, policy)
    run_agent_b(run_dir, policy)
    run_agent_c(run_dir, policy)
    run_agent_d(run_dir, policy)
    run_agent_e(run_dir, policy)
    run_agent_h(run_dir, policy)

    print(f"\n{'=' * 56}")
    print(f"Pipeline Complete — outputs in {run_dir}/")
    print(f"{'=' * 56}\n")
    return run_dir


if __name__ == "__main__":
    bundle = sys.argv[1] if len(sys.argv) > 1 else "inputs/recon_bundle_001"
    run_pipeline(bundle)
