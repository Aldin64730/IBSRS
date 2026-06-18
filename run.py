"""
run.py — one-command entry point for the IBSRS pipeline.

    python run.py                              # default sample bundle
    python run.py inputs/recon_bundle_001      # explicit bundle

Requires an OpenAI API key (OPENAI_MODEL/OPENAI_API_KEY in .env). LLM results are
cached under .cache/llm/, so re-runs with identical inputs don't re-spend tokens.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src", "core"))

from orchestration_scaffolding import run_pipeline  # noqa: E402


def main() -> None:
    bundle = sys.argv[1] if len(sys.argv) > 1 else "inputs/recon_bundle_001"
    run_pipeline(bundle)


if __name__ == "__main__":
    main()
