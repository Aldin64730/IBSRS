"""
config.py
Loads the Policy Pack (config/policy_pack.yaml) and environment (.env).
The policy dict is the single knob-board for tolerances/thresholds — changing a
value here changes decisions without touching agent code.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict


# Repo root = three levels up from this file (src/core/config.py -> repo).
ROOT = Path(__file__).resolve().parents[2]

DEFAULT_POLICY_PATH = ROOT / "config" / "policy_pack.yaml"


def _load_env() -> None:
    """Load .env into os.environ if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass


def load_policy(policy_path: str | os.PathLike | None = None) -> Dict[str, Any]:
    import yaml
    path = Path(policy_path) if policy_path else DEFAULT_POLICY_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class Config:
    """Resolved runtime configuration for a pipeline run."""

    def __init__(self, policy_path: str | os.PathLike | None = None):
        _load_env()
        self.root = ROOT
        self.policy_path = Path(policy_path) if policy_path else DEFAULT_POLICY_PATH
        self.policy = load_policy(self.policy_path)

        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.openai_model = os.environ.get(
            "OPENAI_MODEL",
            self.policy.get("llm", {}).get("model", "gpt-5.4"),
        )
        self.cache_dir = ROOT / ".cache" / "llm"

    def policy_snapshot(self) -> Dict[str, Any]:
        """A copy of the policy for embedding in the audit trail."""
        import copy
        return copy.deepcopy(self.policy)
