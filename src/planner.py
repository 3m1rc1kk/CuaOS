# planner.py — Plan data models, ABC, JSON validation, and system prompt
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ─── Data Models ──────────────────────────────────────────────────────

@dataclass
class PlanStep:
    id: str                                         # e.g. "S1"
    title: str                                      # e.g. "Open browser"
    rationale: str = ""
    preconditions: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    max_attempts: int = 2
    executor_hint: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanStep":
        return cls(
            id=d["id"],
            title=d["title"],
            rationale=d.get("rationale", ""),
            preconditions=d.get("preconditions", []),
            success_criteria=d.get("success_criteria", []),
            max_attempts=d.get("max_attempts", 2),
            executor_hint=d.get("executor_hint", {}),
        )


@dataclass
class Plan:
    objective: str
    steps: List[PlanStep]
    assumptions: List[str] = field(default_factory=list)
    global_stop_conditions: List[str] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "objective": self.objective,
            "assumptions": self.assumptions,
            "steps": [s.to_dict() for s in self.steps],
            "global_stop_conditions": self.global_stop_conditions,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Plan":
        steps = [PlanStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            objective=d["objective"],
            steps=steps,
            assumptions=d.get("assumptions", []),
            global_stop_conditions=d.get("global_stop_conditions", []),
            confidence=float(d.get("confidence", 0.5)),
        )

    def to_json(self, **kw) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, **kw)


# ─── JSON Schema Validation ──────────────────────────────────────────

def validate_plan_json(data: Dict[str, Any]) -> None:
    """Validate a raw dict matches the expected Plan schema. Raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("Plan must be a JSON object")
    if "objective" not in data:
        raise ValueError("Plan missing 'objective'")
    if "steps" not in data or not isinstance(data["steps"], list):
        raise ValueError("Plan missing 'steps' list")
    if len(data["steps"]) == 0:
        raise ValueError("Plan must have at least one step")
    for i, step in enumerate(data["steps"]):
        if not isinstance(step, dict):
            raise ValueError(f"Step {i} is not a JSON object")
        if "id" not in step:
            raise ValueError(f"Step {i} missing 'id'")
        if "title" not in step:
            raise ValueError(f"Step {i} missing 'title'")
        if "success_criteria" not in step or not isinstance(step["success_criteria"], list):
            raise ValueError(f"Step {i} missing 'success_criteria' list")
        if len(step["success_criteria"]) == 0:
            raise ValueError(f"Step {i} must have at least one success_criteria")
    if "confidence" in data:
        c = data["confidence"]
        if not isinstance(c, (int, float)) or c < 0 or c > 1:
            raise ValueError(f"confidence must be 0.0-1.0, got {c}")


# ─── Planner ABC ─────────────────────────────────────────────────────

class Planner(ABC):
    @abstractmethod
    def plan(self, objective: str, context: str = "") -> Plan:
        """Generate a multi-step plan for the given objective."""
        ...


# ─── System Prompt ────────────────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """\
You are a task planner for a Computer Use Agent. The agent controls a Linux XFCE desktop \
via mouse/keyboard actions and observes the screen via screenshots.

Given a user's high-level OBJECTIVE, produce a step-by-step plan as a JSON object.

OUTPUT FORMAT — ONLY valid JSON, no extra text, no markdown, no explanation:
{
  "objective": "<user's objective>",
  "assumptions": ["assumption1", ...],
  "steps": [
    {
      "id": "S1",
      "title": "Short step title",
      "rationale": "Why this step is needed",
      "preconditions": ["what must be true before this step"],
      "success_criteria": ["observable thing on screen that confirms completion"],
      "max_attempts": 2,
      "executor_hint": {
        "preferred_actions": ["CLICK", "TYPE", "HOTKEY"],
        "avoid": []
      }
    }
  ],
  "global_stop_conditions": ["captcha encountered", "permission dialog blocked"],
  "confidence": 0.8
}

RULES:
1. Each step must be ATOMIC — one logical UI operation (e.g., "open browser", "focus address bar").
2. Do NOT combine multiple actions into one step (NO "click X then Y").
3. success_criteria MUST describe things VISIBLE on a screenshot (e.g., "browser window open", "address bar focused with cursor").
4. When uncertain about the UI state, add a DISCOVERY step first (e.g., "observe desktop to locate browser icon").
5. Add WAIT steps after actions that trigger loading (opening apps, navigating pages).
6. max_attempts: 2 for normal steps, 3 for steps that may need loading time.
7. Use executor_hint to guide the executor: prefer HOTKEY when there's a known shortcut.
8. Steps should be high-level intentions, NOT low-level coordinates.
9. Keep plans concise: aim for 3-10 steps. Do not over-decompose trivial tasks.
10. confidence: your confidence that this plan will succeed (0.0-1.0).
11. Output ONLY the JSON object. No other text before or after."""


def build_planner_user_prompt(objective: str, context: str = "") -> str:
    """Build the user prompt for the planner."""
    parts = [f"OBJECTIVE: {objective}"]
    if context:
        parts.append(f"CURRENT CONTEXT: {context}")
    return "\n".join(parts)
