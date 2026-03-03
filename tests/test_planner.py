# tests/test_planner.py — Unit tests for Plan/PlanStep data models and validation
import json
import pytest
import sys
import os

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.planner import Plan, PlanStep, validate_plan_json


# ─── Sample valid plan data ──────────────────────────────────────────

VALID_PLAN_DATA = {
    "objective": "Open YouTube and search for lofi beats",
    "assumptions": ["Browser is installed", "Internet is available"],
    "steps": [
        {
            "id": "S1",
            "title": "Open browser",
            "rationale": "Need a browser to navigate to YouTube",
            "preconditions": ["Desktop is visible"],
            "success_criteria": ["Browser window is open and visible"],
            "max_attempts": 2,
            "executor_hint": {"preferred_actions": ["CLICK"], "avoid": []},
        },
        {
            "id": "S2",
            "title": "Navigate to YouTube",
            "rationale": "Need to go to youtube.com",
            "preconditions": ["Browser is open"],
            "success_criteria": ["Address bar shows youtube.com", "YouTube homepage is visible"],
            "max_attempts": 3,
            "executor_hint": {"preferred_actions": ["HOTKEY", "TYPE"], "avoid": []},
        },
    ],
    "global_stop_conditions": ["captcha encountered"],
    "confidence": 0.85,
}


# ─── PlanStep Tests ──────────────────────────────────────────────────

class TestPlanStep:
    def test_create_step(self):
        step = PlanStep(id="S1", title="Open browser")
        assert step.id == "S1"
        assert step.title == "Open browser"
        assert step.max_attempts == 2
        assert step.success_criteria == []

    def test_to_dict(self):
        step = PlanStep(
            id="S1",
            title="Open browser",
            success_criteria=["Browser visible"],
        )
        d = step.to_dict()
        assert d["id"] == "S1"
        assert d["title"] == "Open browser"
        assert d["success_criteria"] == ["Browser visible"]

    def test_from_dict(self):
        d = VALID_PLAN_DATA["steps"][0]
        step = PlanStep.from_dict(d)
        assert step.id == "S1"
        assert step.title == "Open browser"
        assert step.max_attempts == 2
        assert "Browser window is open and visible" in step.success_criteria

    def test_roundtrip(self):
        original = PlanStep(
            id="S1",
            title="Test step",
            rationale="To test",
            preconditions=["desktop visible"],
            success_criteria=["browser open"],
            max_attempts=3,
            executor_hint={"preferred_actions": ["CLICK"]},
        )
        restored = PlanStep.from_dict(original.to_dict())
        assert original.to_dict() == restored.to_dict()


# ─── Plan Tests ──────────────────────────────────────────────────────

class TestPlan:
    def test_from_dict(self):
        plan = Plan.from_dict(VALID_PLAN_DATA)
        assert plan.objective == "Open YouTube and search for lofi beats"
        assert len(plan.steps) == 2
        assert plan.confidence == 0.85
        assert plan.steps[0].id == "S1"

    def test_to_dict(self):
        plan = Plan.from_dict(VALID_PLAN_DATA)
        d = plan.to_dict()
        assert d["objective"] == VALID_PLAN_DATA["objective"]
        assert len(d["steps"]) == 2
        assert d["confidence"] == 0.85

    def test_roundtrip(self):
        plan = Plan.from_dict(VALID_PLAN_DATA)
        restored = Plan.from_dict(plan.to_dict())
        assert plan.to_dict() == restored.to_dict()

    def test_to_json(self):
        plan = Plan.from_dict(VALID_PLAN_DATA)
        j = plan.to_json()
        parsed = json.loads(j)
        assert parsed["objective"] == VALID_PLAN_DATA["objective"]


# ─── Validation Tests ────────────────────────────────────────────────

class TestValidatePlanJson:
    def test_valid(self):
        validate_plan_json(VALID_PLAN_DATA)  # Should not raise

    def test_missing_objective(self):
        data = {k: v for k, v in VALID_PLAN_DATA.items() if k != "objective"}
        with pytest.raises(ValueError, match="missing 'objective'"):
            validate_plan_json(data)

    def test_missing_steps(self):
        data = {k: v for k, v in VALID_PLAN_DATA.items() if k != "steps"}
        with pytest.raises(ValueError, match="missing 'steps'"):
            validate_plan_json(data)

    def test_empty_steps(self):
        data = {**VALID_PLAN_DATA, "steps": []}
        with pytest.raises(ValueError, match="at least one step"):
            validate_plan_json(data)

    def test_step_missing_id(self):
        bad_step = {"title": "Test", "success_criteria": ["x"]}
        data = {**VALID_PLAN_DATA, "steps": [bad_step]}
        with pytest.raises(ValueError, match="missing 'id'"):
            validate_plan_json(data)

    def test_step_missing_title(self):
        bad_step = {"id": "S1", "success_criteria": ["x"]}
        data = {**VALID_PLAN_DATA, "steps": [bad_step]}
        with pytest.raises(ValueError, match="missing 'title'"):
            validate_plan_json(data)

    def test_step_missing_success_criteria(self):
        bad_step = {"id": "S1", "title": "Test"}
        data = {**VALID_PLAN_DATA, "steps": [bad_step]}
        with pytest.raises(ValueError, match="missing 'success_criteria'"):
            validate_plan_json(data)

    def test_step_empty_success_criteria(self):
        bad_step = {"id": "S1", "title": "Test", "success_criteria": []}
        data = {**VALID_PLAN_DATA, "steps": [bad_step]}
        with pytest.raises(ValueError, match="at least one success_criteria"):
            validate_plan_json(data)

    def test_invalid_confidence_high(self):
        data = {**VALID_PLAN_DATA, "confidence": 1.5}
        with pytest.raises(ValueError, match="0.0-1.0"):
            validate_plan_json(data)

    def test_invalid_confidence_negative(self):
        data = {**VALID_PLAN_DATA, "confidence": -0.1}
        with pytest.raises(ValueError, match="0.0-1.0"):
            validate_plan_json(data)

    def test_not_a_dict(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            validate_plan_json("not a dict")
