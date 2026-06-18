"""
llm.py
A deliberately tiny OpenAI wrapper. One public function: complete().

Determinism + cost control come from two choices:
  1. temperature=0
  2. every call is keyed by sha256(model, system, user); results are cached on
     disk under .cache/llm/, so a re-run with identical inputs never re-spends
     tokens and never drifts.

complete() always calls the OpenAI API (cache misses only). Errors are not
swallowed — a missing key, bad model, or network/quota failure raises so the
problem is visible rather than masquerading as a successful run.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from config import Config


def _key(model: str, system: str, user: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(system.encode("utf-8"))
    h.update(b"\x00")
    h.update(user.encode("utf-8"))
    return h.hexdigest()


class LLM:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.cache_dir: Path = self.config.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def complete(self, system: str, user: str, *, purpose: str = "") -> str:
        """Return model text for (system, user). Cached + deterministic."""
        model = self.config.openai_model
        key = _key(model, system, user)
        cache_file = self.cache_dir / f"{key}.json"

        if cache_file.exists():
            return json.loads(cache_file.read_text(encoding="utf-8"))["output"]

        text = self._generate(system, user, purpose=purpose)

        cache_file.write_text(
            json.dumps({"purpose": purpose, "model": model, "output": text}, indent=2),
            encoding="utf-8",
        )
        return text

    # ------------------------------------------------------------------ #
    def _generate(self, system: str, user: str, *, purpose: str) -> str:
        if not self.config.openai_api_key:
            raise RuntimeError(
                "No OpenAI API key configured (set OPENAI_API_KEY in .env)."
            )
        from openai import OpenAI
        client = OpenAI(api_key=self.config.openai_api_key)
        resp = client.chat.completions.create(
            model=self.config.openai_model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""
