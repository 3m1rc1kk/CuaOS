# agent_loop.py — Hierarchical Planner → Executor → Verifier orchestrator
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, List, Optional

from src.config import cfg
from src.sandbox import Sandbox
from src.llm_client import ask_next_action
from src.vision import capture_screen, draw_preview
from src.guards import validate_xy, should_stop_on_repeat
from src.actions import execute_action
from src.planner import Plan, PlanStep, Planner
from src.verifier import verify_step, VerifierResult


# ─── History helpers ─────────────────────────────────────────────────

def _trim_history(history: List[Dict[str, Any]], keep_last: int = 6) -> List[Dict[str, Any]]:
    return history[-keep_last:] if len(history) > keep_last else history


# ─── Build enriched executor objective ───────────────────────────────

def _build_executor_objective(original_objective: str, step: PlanStep, verifier_hint: str = "") -> str:
    """
    Build the enriched objective for the executor (ask_next_action).
    Passes step-specific context so the vision model knows exactly what to do.
    """
    criteria_str = "; ".join(step.success_criteria)
    parts = [
        f"OVERALL OBJECTIVE: {original_objective}",
        f"CURRENT_STEP: {step.title}",
        f"SUCCESS_CRITERIA: {criteria_str}",
    ]

    if step.executor_hint:
        preferred = step.executor_hint.get("preferred_actions", [])
        avoid = step.executor_hint.get("avoid", [])
        if preferred:
            parts.append(f"PREFERRED_ACTIONS: {', '.join(preferred)}")
        if avoid:
            parts.append(f"AVOID: {', '.join(avoid)}")

    if verifier_hint:
        parts.append(f"PREVIOUS_ATTEMPT_FEEDBACK: {verifier_hint}")

    parts.append("Execute the CURRENT_STEP. Output ONLY one JSON action.")
    return "\n".join(parts)


# ─── Orchestrator ────────────────────────────────────────────────────

def run_agent_loop(
    sandbox: Sandbox,
    llm,
    planner: Planner,
    objective: str,
    log_fn: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Hierarchical agent loop:
    1. Generate plan
    2. For each step: execute → verify → advance/retry/replan
    Returns final status string.
    """

    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)
        print(msg)

    max_replan = getattr(cfg, "PLANNER_MAX_REPLAN", 2)
    global_step_count = 0
    replan_count = 0

    # ── Initial plan ──────────────────────────────────────────────
    _log(f"\n{'='*60}")
    _log(f"[AGENT] Objective: {objective}")
    _log(f"{'='*60}")

    context = ""  # Will be enriched on replans

    while replan_count <= max_replan:
        # Generate / regenerate plan
        _log(f"\n[PLANNER] {'Generating' if replan_count == 0 else 'Re-generating'} plan (attempt {replan_count + 1})...")

        try:
            plan = planner.plan(objective, context)
        except Exception as e:
            _log(f"[PLANNER] ERROR: Plan generation failed: {e}")
            return f"ERROR(planner_failed: {e})"

        _log(f"[PLANNER] Plan generated (confidence={plan.confidence:.2f}, steps={len(plan.steps)}):")
        _log(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))

        # ── Execute plan steps ────────────────────────────────────
        result = _execute_plan(
            sandbox=sandbox,
            llm=llm,
            plan=plan,
            objective=objective,
            global_step_count=global_step_count,
            log_fn=_log,
        )

        global_step_count = result["global_step_count"]
        status = result["status"]

        if status == "COMPLETED":
            _log(f"\n[AGENT] ✓ Objective completed successfully!")
            return "DONE"

        if status == "MAX_STEPS_EXCEEDED":
            _log(f"\n[AGENT] MAX_STEPS ({cfg.MAX_STEPS}) exceeded globally.")
            return "DONE(max_steps)"

        if status == "NEEDS_REPLAN":
            replan_count += 1
            # Build context for replanning
            stuck_step = result.get("stuck_step", "")
            failure = result.get("failure_info", "")
            context = (
                f"Previous plan got stuck at step: {stuck_step}. "
                f"Failure: {failure}. "
                f"Total actions so far: {global_step_count}. "
                "Please adjust the plan to work around this issue."
            )
            _log(f"\n[AGENT] Replanning... ({replan_count}/{max_replan})")
            continue

        # Unknown status
        _log(f"\n[AGENT] Unexpected status: {status}")
        return f"ERROR({status})"

    _log(f"\n[AGENT] Max replans ({max_replan}) exhausted. Giving up.")
    return "ERROR(max_replans)"


def _execute_plan(
    sandbox: Sandbox,
    llm,
    plan: Plan,
    objective: str,
    global_step_count: int,
    log_fn: Callable[[str], None],
) -> Dict[str, Any]:
    """
    Execute all steps in a plan.
    Returns dict with:
      - status: "COMPLETED" | "MAX_STEPS_EXCEEDED" | "NEEDS_REPLAN"
      - global_step_count: updated count
      - stuck_step: step title if stuck (for replan context)
      - failure_info: last verifier failure info
    """
    history: List[Dict[str, Any]] = []

    for step_idx, step in enumerate(plan.steps):
        log_fn(f"\n{'─'*50}")
        log_fn(f"[STEP {step.id}] {step.title}")
        log_fn(f"  Success criteria: {step.success_criteria}")
        log_fn(f"  Max attempts: {step.max_attempts}")

        # Check global stop conditions
        # (These are checked textually against verifier evidence later)

        attempts = 0
        verifier_hint = ""
        step_done = False

        while attempts < step.max_attempts:
            attempts += 1
            global_step_count += 1

            # Safety: global step limit
            if global_step_count > cfg.MAX_STEPS:
                return {
                    "status": "MAX_STEPS_EXCEEDED",
                    "global_step_count": global_step_count,
                }

            log_fn(f"\n  [ATTEMPT {attempts}/{step.max_attempts}] (global action #{global_step_count})")

            # ── 1. Capture screenshot ─────────────────────────────
            time.sleep(cfg.WAIT_BEFORE_SCREENSHOT_SEC)
            img = capture_screen(sandbox, cfg.SCREENSHOT_PATH)

            # ── 2. Ask executor for next action ───────────────────
            enriched_objective = _build_executor_objective(objective, step, verifier_hint)

            out: Optional[Dict[str, Any]] = None
            for retry in range(cfg.MODEL_RETRY + 1):
                out = ask_next_action(llm, enriched_objective, cfg.SCREENSHOT_PATH, _trim_history(history))
                action = (out.get("action") or "NOOP").upper()

                # If executor says BITTI, treat step as done
                if action == "BITTI":
                    log_fn(f"  [EXECUTOR] BITTI → executor believes step is done")
                    step_done = True
                    break

                # Validate coordinates for click actions
                if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                    x = float(out.get("x", 0.5))
                    y = float(out.get("y", 0.5))
                    ok, reason = validate_xy(x, y)
                    if ok:
                        break
                    log_fn(f"  [WARN] Invalid coordinates ({reason}), retrying executor...")
                    history.append({"action": "INVALID_COORDS", "raw": out})
                    out = None
                    continue

                # Other action types accepted
                break

            if step_done:
                log_fn(f"  [STEP {step.id}] ✓ Executor says done (BITTI), advancing.")
                break

            if out is None:
                log_fn(f"  [ERROR] Executor could not produce valid action.")
                verifier_hint = "Executor failed to produce a valid action, try a different approach."
                continue

            log_fn(f"  [EXECUTOR] {json.dumps(out, ensure_ascii=False)}")

            # ── 3. Apply repeat guard ─────────────────────────────
            stop, why = should_stop_on_repeat(history, out)
            if stop:
                log_fn(f"  [GUARD] {why}")
                verifier_hint = f"Action was blocked by repeat guard: {why}. Try something different."
                continue

            # ── 4. Draw preview (optional) ────────────────────────
            action = (out.get("action") or "").upper()
            if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                preview_path = cfg.PREVIEW_PATH_TEMPLATE.format(i=global_step_count)
                draw_preview(img, float(out["x"]), float(out["y"]), preview_path)

            # ── 5. Execute action ─────────────────────────────────
            execute_action(sandbox, out)
            history.append(out)

            # ── 6. Capture post-action screenshot ─────────────────
            time.sleep(cfg.WAIT_BEFORE_SCREENSHOT_SEC)
            capture_screen(sandbox, cfg.SCREENSHOT_PATH)

            # ── 7. Verify step completion ─────────────────────────
            log_fn(f"  [VERIFIER] Checking step completion...")
            try:
                vr: VerifierResult = verify_step(llm, step, cfg.SCREENSHOT_PATH)
            except Exception as e:
                log_fn(f"  [VERIFIER] ERROR: {e}")
                vr = VerifierResult(
                    step_id=step.id,
                    done=False,
                    evidence=[f"verifier error: {e}"],
                    failure_type="OTHER",
                    suggested_fix="retry the step",
                    confidence=0.1,
                )

            log_fn(f"  [VERIFIER] done={vr.done}, confidence={vr.confidence:.2f}, "
                   f"failure_type={vr.failure_type}")
            if vr.evidence:
                log_fn(f"  [VERIFIER] evidence: {vr.evidence}")

            # ── 8. Check global stop conditions ───────────────────
            if _check_global_stop(plan, vr):
                log_fn(f"  [AGENT] Global stop condition triggered!")
                return {
                    "status": "NEEDS_REPLAN",
                    "global_step_count": global_step_count,
                    "stuck_step": step.title,
                    "failure_info": f"Global stop: {vr.evidence}",
                }

            if vr.done:
                log_fn(f"  [STEP {step.id}] ✓ Verified as complete!")
                step_done = True
                break
            else:
                # Build hint for next attempt
                verifier_hint = (
                    f"Previous attempt did NOT satisfy success criteria. "
                    f"Failure: {vr.failure_type}. "
                    f"Suggestion: {vr.suggested_fix}. "
                    f"Evidence: {'; '.join(vr.evidence)}"
                )
                log_fn(f"  [STEP {step.id}] ✗ Not done yet. {verifier_hint}")

        # After all attempts for this step
        if not step_done:
            log_fn(f"\n  [STEP {step.id}] ✗ Failed after {step.max_attempts} attempts → triggering replan.")
            return {
                "status": "NEEDS_REPLAN",
                "global_step_count": global_step_count,
                "stuck_step": step.title,
                "failure_info": verifier_hint or "max attempts exhausted",
            }

    # All steps completed
    return {
        "status": "COMPLETED",
        "global_step_count": global_step_count,
    }


def _check_global_stop(plan: Plan, vr: VerifierResult) -> bool:
    """Check if any global stop condition is mentioned in verifier evidence."""
    if not plan.global_stop_conditions or not vr.evidence:
        return False
    evidence_lower = " ".join(vr.evidence).lower()
    for condition in plan.global_stop_conditions:
        if condition.lower() in evidence_lower:
            return True
    return False
