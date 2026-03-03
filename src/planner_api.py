# planner_api.py — API-based planner for OpenRouter / OpenAI
from __future__ import annotations

import json
from typing import Any, Dict

import requests

from src.config import cfg, JSON_RE
from src.planner import (
    Plan,
    Planner,
    PLANNER_SYSTEM_PROMPT,
    build_planner_user_prompt,
    validate_plan_json,
)


# ─── API endpoints ───────────────────────────────────────────────────

_API_URLS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}


class APIPlanner(Planner):
    """Plan generation via OpenRouter or OpenAI API (HTTP)."""

    def __init__(self):
        provider = cfg.PLANNER_PROVIDER.lower()
        self._api_key = cfg.PLANNER_API_KEY
        self._model = cfg.PLANNER_MODEL
        self._max_tokens = cfg.PLANNER_MAX_TOKENS

        if not self._api_key:
            raise ValueError("PLANNER_API_KEY must be set to use the API planner.")
        if not self._model:
            raise ValueError("PLANNER_MODEL must be set to use the API planner.")

        self._url = _API_URLS.get(provider)
        if not self._url:
            raise ValueError(
                f"Unknown PLANNER_PROVIDER '{provider}'. "
                f"Supported: {', '.join(_API_URLS.keys())}"
            )

        self._headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # OpenRouter requires HTTP-Referer for some models
        if provider == "openrouter":
            self._headers["HTTP-Referer"] = "https://github.com/CuaOS/CuaOS"
            self._headers["X-Title"] = "CuaOS Agent"

        print(f"[PLANNER] API planner ready (provider={provider}, model={self._model})")

    def plan(self, objective: str, context: str = "") -> Plan:
        user_prompt = build_planner_user_prompt(objective, context)

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": self._max_tokens,
        }

        resp = requests.post(self._url, headers=self._headers, json=payload, timeout=60)
        resp.raise_for_status()

        data = resp.json()
        raw_text = data["choices"][0]["message"]["content"]
        return self._parse_plan(raw_text, objective)

    @staticmethod
    def _parse_plan(raw_text: str, objective: str) -> Plan:
        """Parse JSON plan from raw API output."""
        m = JSON_RE.search(raw_text.strip())
        if not m:
            raise ValueError(f"API planner output is not valid JSON:\n{raw_text[:500]}")

        plan_data: Dict[str, Any] = json.loads(m.group(0))
        plan_data.setdefault("objective", objective)

        validate_plan_json(plan_data)
        return Plan.from_dict(plan_data)
