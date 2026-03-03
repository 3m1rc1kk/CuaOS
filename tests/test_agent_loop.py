# tests/test_agent_loop.py — Unit tests for orchestrator step logic (fully mocked)
import json
import pytest
import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.planner import Plan, PlanStep, Planner
from src.verifier import VerifierResult
from src.agent_loop import _build_executor_objective, _check_global_stop, _execute_plan


# ─── Mock helpers ────────────────────────────────────────────────────

class MockPlanner(Planner):
    """A mock planner that returns a pre-defined plan."""

    def __init__(self, plan: Plan):
        self._plan = plan

    def plan(self, objective: str, context: str = "") -> Plan:
        return self._plan


def _make_plan(num_steps=2, max_attempts=2):
    steps = []
    for i in range(1, num_steps + 1):
        steps.append(PlanStep(
            id=f"S{i}",
            title=f"Step {i}",
            success_criteria=[f"Step {i} is done"],
            max_attempts=max_attempts,
        ))
    return Plan(
        objective="Test objective",
        steps=steps,
        global_stop_conditions=["captcha encountered"],
        confidence=0.9,
    )


def _mock_cfg():
    """Create a mock cfg object with required attributes."""
    mock = MagicMock()
    mock.MAX_STEPS = 50
    mock.WAIT_BEFORE_SCREENSHOT_SEC = 0.0
    mock.SCREENSHOT_PATH = "/tmp/test_screen.png"
    mock.MODEL_RETRY = 1
    mock.MIN_MARGIN = 0.02
    mock.STOP_ON_REPEAT = True
    mock.REPEAT_XY_EPS = 0.01
    mock.PREVIEW_PATH_TEMPLATE = "/tmp/preview_{i}.png"
    mock.PLANNER_MAX_REPLAN = 2
    return mock


# ─── Test _build_executor_objective ──────────────────────────────────

class TestBuildExecutorObjective:
    def test_basic(self):
        step = PlanStep(
            id="S1",
            title="Open browser",
            success_criteria=["Browser window is visible"],
        )
        result = _build_executor_objective("Open YouTube", step)
        assert "OVERALL OBJECTIVE: Open YouTube" in result
        assert "CURRENT_STEP: Open browser" in result
        assert "SUCCESS_CRITERIA: Browser window is visible" in result

    def test_with_hint(self):
        step = PlanStep(id="S1", title="Test", success_criteria=["done"])
        result = _build_executor_objective("obj", step, verifier_hint="try clicking elsewhere")
        assert "PREVIOUS_ATTEMPT_FEEDBACK: try clicking elsewhere" in result

    def test_with_executor_hint(self):
        step = PlanStep(
            id="S1",
            title="Test",
            success_criteria=["done"],
            executor_hint={"preferred_actions": ["HOTKEY"], "avoid": ["CLICK"]},
        )
        result = _build_executor_objective("obj", step)
        assert "PREFERRED_ACTIONS: HOTKEY" in result
        assert "AVOID: CLICK" in result


# ─── Test _check_global_stop ─────────────────────────────────────────

class TestCheckGlobalStop:
    def test_no_stop_conditions(self):
        plan = Plan(objective="test", steps=[], global_stop_conditions=[])
        vr = VerifierResult(step_id="S1", done=False, evidence=["captcha visible"])
        assert _check_global_stop(plan, vr) is False

    def test_stop_condition_matched(self):
        plan = Plan(
            objective="test",
            steps=[],
            global_stop_conditions=["captcha encountered"],
        )
        vr = VerifierResult(step_id="S1", done=False, evidence=["captcha encountered on screen"])
        assert _check_global_stop(plan, vr) is True

    def test_stop_condition_not_matched(self):
        plan = Plan(
            objective="test",
            steps=[],
            global_stop_conditions=["captcha encountered"],
        )
        vr = VerifierResult(step_id="S1", done=False, evidence=["browser window visible"])
        assert _check_global_stop(plan, vr) is False


# ─── Test _execute_plan step advancement ─────────────────────────────

class TestExecutePlan:
    @patch("src.agent_loop.cfg")
    @patch("src.agent_loop.verify_step")
    @patch("src.agent_loop.execute_action")
    @patch("src.agent_loop.capture_screen")
    @patch("src.agent_loop.draw_preview")
    @patch("src.agent_loop.ask_next_action")
    @patch("src.agent_loop.should_stop_on_repeat", return_value=(False, ""))
    @patch("src.agent_loop.validate_xy", return_value=(True, ""))
    def test_all_steps_complete(
        self, mock_validate, mock_repeat, mock_ask, mock_preview,
        mock_capture, mock_exec, mock_verify, mock_cfg
    ):
        """When verifier returns done=True for each step, all steps complete."""
        mock_cfg.MAX_STEPS = 50
        mock_cfg.WAIT_BEFORE_SCREENSHOT_SEC = 0.0
        mock_cfg.SCREENSHOT_PATH = "/tmp/x.png"
        mock_cfg.MODEL_RETRY = 1
        mock_cfg.PREVIEW_PATH_TEMPLATE = "/tmp/p_{i}.png"

        mock_capture.return_value = MagicMock()
        mock_ask.return_value = {"action": "CLICK", "x": 0.5, "y": 0.5, "target": "button"}

        # Verifier says done for each step
        mock_verify.return_value = VerifierResult(
            step_id="S1", done=True, evidence=["done"], confidence=0.9
        )

        plan = _make_plan(num_steps=2)
        sandbox = MagicMock()

        result = _execute_plan(
            sandbox=sandbox,
            llm=MagicMock(),
            plan=plan,
            objective="test",
            global_step_count=0,
            log_fn=lambda msg: None,
        )

        assert result["status"] == "COMPLETED"

    @patch("src.agent_loop.cfg")
    @patch("src.agent_loop.verify_step")
    @patch("src.agent_loop.execute_action")
    @patch("src.agent_loop.capture_screen")
    @patch("src.agent_loop.draw_preview")
    @patch("src.agent_loop.ask_next_action")
    @patch("src.agent_loop.should_stop_on_repeat", return_value=(False, ""))
    @patch("src.agent_loop.validate_xy", return_value=(True, ""))
    def test_step_fails_triggers_replan(
        self, mock_validate, mock_repeat, mock_ask, mock_preview,
        mock_capture, mock_exec, mock_verify, mock_cfg
    ):
        """When verifier returns done=False for all attempts, triggers replan."""
        mock_cfg.MAX_STEPS = 50
        mock_cfg.WAIT_BEFORE_SCREENSHOT_SEC = 0.0
        mock_cfg.SCREENSHOT_PATH = "/tmp/x.png"
        mock_cfg.MODEL_RETRY = 1
        mock_cfg.PREVIEW_PATH_TEMPLATE = "/tmp/p_{i}.png"

        mock_capture.return_value = MagicMock()
        mock_ask.return_value = {"action": "CLICK", "x": 0.5, "y": 0.5, "target": "button"}

        # Verifier always says not done
        mock_verify.return_value = VerifierResult(
            step_id="S1",
            done=False,
            evidence=["nothing happened"],
            failure_type="NOT_FOUND",
            suggested_fix="try different element",
            confidence=0.3,
        )

        plan = _make_plan(num_steps=2, max_attempts=2)
        sandbox = MagicMock()

        result = _execute_plan(
            sandbox=sandbox,
            llm=MagicMock(),
            plan=plan,
            objective="test",
            global_step_count=0,
            log_fn=lambda msg: None,
        )

        assert result["status"] == "NEEDS_REPLAN"
        assert "Step 1" in result["stuck_step"]

    @patch("src.agent_loop.cfg")
    @patch("src.agent_loop.verify_step")
    @patch("src.agent_loop.execute_action")
    @patch("src.agent_loop.capture_screen")
    @patch("src.agent_loop.draw_preview")
    @patch("src.agent_loop.ask_next_action")
    @patch("src.agent_loop.should_stop_on_repeat", return_value=(False, ""))
    @patch("src.agent_loop.validate_xy", return_value=(True, ""))
    def test_max_steps_exceeded(
        self, mock_validate, mock_repeat, mock_ask, mock_preview,
        mock_capture, mock_exec, mock_verify, mock_cfg
    ):
        """When global MAX_STEPS is exceeded, stops immediately."""
        mock_cfg.MAX_STEPS = 1  # Very low
        mock_cfg.WAIT_BEFORE_SCREENSHOT_SEC = 0.0
        mock_cfg.SCREENSHOT_PATH = "/tmp/x.png"
        mock_cfg.MODEL_RETRY = 1
        mock_cfg.PREVIEW_PATH_TEMPLATE = "/tmp/p_{i}.png"

        mock_capture.return_value = MagicMock()
        mock_ask.return_value = {"action": "CLICK", "x": 0.5, "y": 0.5, "target": "button"}
        mock_verify.return_value = VerifierResult(
            step_id="S1", done=False, evidence=["pending"], confidence=0.5
        )

        plan = _make_plan(num_steps=5, max_attempts=3)
        sandbox = MagicMock()

        result = _execute_plan(
            sandbox=sandbox,
            llm=MagicMock(),
            plan=plan,
            objective="test",
            global_step_count=0,
            log_fn=lambda msg: None,
        )

        assert result["status"] == "MAX_STEPS_EXCEEDED"

    @patch("src.agent_loop.cfg")
    @patch("src.agent_loop.execute_action")
    @patch("src.agent_loop.capture_screen")
    @patch("src.agent_loop.draw_preview")
    @patch("src.agent_loop.ask_next_action")
    @patch("src.agent_loop.should_stop_on_repeat", return_value=(False, ""))
    @patch("src.agent_loop.validate_xy", return_value=(True, ""))
    def test_executor_bitti_advances_step(
        self, mock_validate, mock_repeat, mock_ask, mock_preview,
        mock_capture, mock_exec, mock_cfg
    ):
        """When executor returns BITTI, current step is considered done."""
        mock_cfg.MAX_STEPS = 50
        mock_cfg.WAIT_BEFORE_SCREENSHOT_SEC = 0.0
        mock_cfg.SCREENSHOT_PATH = "/tmp/x.png"
        mock_cfg.MODEL_RETRY = 1
        mock_cfg.PREVIEW_PATH_TEMPLATE = "/tmp/p_{i}.png"

        mock_capture.return_value = MagicMock()
        mock_ask.return_value = {"action": "BITTI"}

        plan = _make_plan(num_steps=2)
        sandbox = MagicMock()

        result = _execute_plan(
            sandbox=sandbox,
            llm=MagicMock(),
            plan=plan,
            objective="test",
            global_step_count=0,
            log_fn=lambda msg: None,
        )

        assert result["status"] == "COMPLETED"
