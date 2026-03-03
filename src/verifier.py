# verifier.py — Vision-based step verification using existing Qwen3-VL model
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

from llama_cpp import Llama

from src.config import JSON_RE
from src.planner import PlanStep
from src.vision import image_to_data_uri


# ─── Failure types ───────────────────────────────────────────────────

FAILURE_TYPES = {"NONE", "NOT_FOUND", "WRONG_WINDOW", "DIALOG_BLOCKING", "LOADING", "NETWORK", "OTHER"}


# ─── VerifierResult Data Model ───────────────────────────────────────

@dataclass
class VerifierResult:
    step_id: str
    done: bool
    evidence: List[str] = field(default_factory=list)
    failure_type: str = "NONE"
    suggested_fix: str = ""
    confidence: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "VerifierResult":
        return cls(
            step_id=d["step_id"],
            done=bool(d["done"]),
            evidence=d.get("evidence", []),
            failure_type=d.get("failure_type", "NONE"),
            suggested_fix=d.get("suggested_fix", ""),
            confidence=float(d.get("confidence", 0.5)),
        )


def validate_verifier_json(data: Dict[str, Any]) -> None:
    """Validate a raw dict matches the VerifierResult schema. Raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("VerifierResult must be a JSON object")
    if "step_id" not in data:
        raise ValueError("VerifierResult missing 'step_id'")
    if "done" not in data:
        raise ValueError("VerifierResult missing 'done'")
    if not isinstance(data["done"], bool):
        raise ValueError(f"'done' must be a boolean, got {type(data['done']).__name__}")
    if "evidence" in data and not isinstance(data["evidence"], list):
        raise ValueError("'evidence' must be a list")
    ft = data.get("failure_type", "NONE")
    if ft not in FAILURE_TYPES:
        raise ValueError(f"Invalid failure_type '{ft}'. Must be one of: {FAILURE_TYPES}")
    if "confidence" in data:
        c = data["confidence"]
        if not isinstance(c, (int, float)) or c < 0 or c > 1:
            raise ValueError(f"confidence must be 0.0-1.0, got {c}")


# ─── Verifier System Prompt ──────────────────────────────────────────

VERIFIER_SYSTEM_PROMPT = """\
You are a verification agent for a Computer Use Agent. You are given:
1. A STEP that was just attempted (with its title and success_criteria).
2. A SCREENSHOT of the current screen state.

Your job is to decide if the step is DONE or NOT by examining the screenshot.

OUTPUT FORMAT — ONLY valid JSON, no extra text, no markdown:
{
  "step_id": "<step id>",
  "done": true or false,
  "evidence": ["short bullet citing visible screen cue", ...],
  "failure_type": "NONE|NOT_FOUND|WRONG_WINDOW|DIALOG_BLOCKING|LOADING|NETWORK|OTHER",
  "suggested_fix": "one short suggestion if not done, empty if done",
  "confidence": 0.0-1.0
}

RULES:
1. Output ONLY the JSON object. No other text.
2. "evidence" must cite specific things you SEE on the screenshot (e.g., "Firefox window visible", "address bar shows youtube.com").
3. "done" is true ONLY if ALL success_criteria are visibly satisfied in the screenshot.
4. If done is true, failure_type MUST be "NONE" and suggested_fix MUST be empty.
5. If done is false, choose the most appropriate failure_type and suggest ONE brief fix.
6. Be conservative: if uncertain, set done to false with lower confidence."""


def _build_verifier_prompt(step: PlanStep) -> str:
    criteria_str = "\n".join(f"  - {c}" for c in step.success_criteria)
    return (
        f"STEP ID: {step.id}\n"
        f"STEP TITLE: {step.title}\n"
        f"SUCCESS CRITERIA:\n{criteria_str}\n\n"
        "Examine the screenshot and determine if this step is complete."
    )


# ─── Verify Step Function ────────────────────────────────────────────

def verify_step(llm: Llama, step: PlanStep, screenshot_path: str) -> VerifierResult:
    """
    Use the existing Qwen3-VL vision model to verify whether a plan step
    has been completed based on the current screenshot.
    """
    uri = image_to_data_uri(screenshot_path)
    user_prompt = _build_verifier_prompt(step)

    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": uri}},
                {"type": "text", "text": user_prompt},
            ]},
        ],
        temperature=0.1,
        top_p=0.9,
        max_tokens=300,
        stop=["\n\n", "<|im_end|>"],
    )

    raw_text = resp["choices"][0]["message"]["content"]
    return _parse_verifier_output(raw_text, step.id)


def _parse_verifier_output(raw_text: str, fallback_step_id: str) -> VerifierResult:
    """Parse verifier JSON from raw LLM output."""
    m = JSON_RE.search(raw_text.strip())
    if not m:
        # Fallback: if parsing fails, assume step NOT done
        print(f"[VERIFIER] WARNING: Could not parse JSON from verifier output, assuming not done.")
        return VerifierResult(
            step_id=fallback_step_id,
            done=False,
            evidence=["verifier output was not valid JSON"],
            failure_type="OTHER",
            suggested_fix="retry the step",
            confidence=0.1,
        )

    data = json.loads(m.group(0))
    data.setdefault("step_id", fallback_step_id)

    try:
        validate_verifier_json(data)
    except ValueError as e:
        print(f"[VERIFIER] WARNING: Invalid verifier JSON ({e}), assuming not done.")
        return VerifierResult(
            step_id=fallback_step_id,
            done=False,
            evidence=[f"verifier JSON validation failed: {e}"],
            failure_type="OTHER",
            suggested_fix="retry the step",
            confidence=0.1,
        )

    return VerifierResult.from_dict(data)
