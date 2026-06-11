"""
orchestration_scaffolding.py
Runs the 6-agent pipeline in sequence.
Each agent reads from and writes to the shared run directory.
"""

import os
from datetime import datetime
from file_utils import read_yaml

# Import all agents
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), "../agents"))

from agent_a_gatekeeper import run as run_agent_a
from agent_b_extractor import run as run_agent_b
from agent_c_gl_matcher import run as run_agent_c
from agent_d_variance import run as run_agent_d
from agent_e_duplicates import run as run_agent_e
from agent_h_orchestrator import run as run_agent_h


def run_pipeline(bundle_path: str, policy_path: str = "config/policy_pack.yaml"):
    # Create timestamped run directory
    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = f"runs/{run_id}"
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(f"{run_dir}/findings", exist_ok=True)
    os.makedirs(f"{run_dir}/logs", exist_ok=True)

    print(f"\n{'='*50}")
    print(f"IBSRS Pipeline Starting — {run_id}")
    print(f"Bundle: {bundle_path}")
    print(f"{'='*50}\n")

    policy = read_yaml(policy_path)

    # Sequential agent execution
    run_agent_a(bundle_path, run_dir, policy)
    run_agent_b(run_dir, policy)
    run_agent_c(run_dir, policy)
    run_agent_d(run_dir, policy)
    run_agent_e(run_dir, policy)
    run_agent_h(run_dir, policy)

    print(f"\n{'='*50}")
    print(f"Pipeline Complete — outputs in {run_dir}/")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run_pipeline("inputs/recon_bundle_001")
