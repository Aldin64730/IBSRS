"""
agent_a_gatekeeper.py
Statement Intake & Context Packet Construction.
TODO: Implement this agent.
"""

def run(bundle_path: str, run_dir: str, policy: dict) -> None:
    print(f"[Agent A] Starting — reading bundle from {bundle_path}...")
    # 1. Read manifest.yaml from bundle_path
    # 2. Validate all required files are present
    # 3. Call OpenAI API with agent_a_prompt.txt
    # 4. Write context_packet.json to run_dir
    # 5. Append to run_dir/logs/agent_a.log
    print(f"[Agent A] Done.")
