# main.py
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.config import cfg
from src.sandbox import Sandbox
from src.llm_client import load_llm, ask_next_action
from src.vision import capture_screen, draw_preview
from src.guards import validate_xy, should_stop_on_repeat
from src.actions import execute_action


# Trim conversation history to avoid exceeding context length
def trim_history(history, keep_last=6):
    if len(history) <= keep_last:
        return history
    return history[-keep_last:]


def _create_planner():
    """Create a planner instance based on config. Returns None if not configured."""
    from src.planner import Planner

    provider = cfg.PLANNER_PROVIDER.lower()

    if provider == "local":
        from src.planner_local import LocalGGUFPlanner
        return LocalGGUFPlanner()
    elif provider in ("openrouter", "openai"):
        from src.planner_api import APIPlanner
        return APIPlanner()
    else:
        print(f"[WARN] Unknown PLANNER_PROVIDER '{provider}', falling back to reactive mode.")
        return None


def main() -> None:
    sandbox = Sandbox(cfg)
    sandbox.start()

    # Launch VNC viewer window (optional/noVNC)
    if getattr(cfg, "OPEN_VNC_VIEWER", True):
        sandbox.launch_vnc_viewer()

    llm = load_llm()
    print("[DEBUG] cfg.N_CTX =", cfg.N_CTX)

    # ── Set up planner if enabled ─────────────────────────────
    planner = None
    if cfg.USE_PLANNER:
        try:
            planner = _create_planner()
            if planner:
                print("[PLANNER] Hierarchical planning mode ENABLED.")
            else:
                print("[PLANNER] Could not create planner. Falling back to reactive mode.")
        except Exception as e:
            print(f"[PLANNER] ERROR creating planner: {e}")
            print("[PLANNER] Falling back to reactive mode.")

    print("Agent ready. Type 'exit' or 'quit' to quit.")

    # Main loop: runs until user exits
    while True:
        objective = input("\nEnter command (or 'quit'): ").strip()

        # Recognize user exit
        if not objective:
            print("Command cannot be empty. Try again.")
            continue
        low = objective.lower()
        if low in ("exit", "quit", "q"):
            print("Agent shutting down.")
            break

        # ── Planning mode ─────────────────────────────────────
        if planner is not None:
            from src.agent_loop import run_agent_loop
            result = run_agent_loop(
                sandbox=sandbox,
                llm=llm,
                planner=planner,
                objective=objective,
            )
            print(f"\n[AGENT] Final result: {result}")
            print("Ready for the next command.")
            continue

        # ── Reactive mode (original behavior) ─────────────────
        history: List[Dict[str, Any]] = []

        step = 1
        while True:
            print(f"\n==================== STEP {step} ====================")

            time.sleep(cfg.WAIT_BEFORE_SCREENSHOT_SEC)

            # Capture current screenshot
            img = capture_screen(sandbox, cfg.SCREENSHOT_PATH)

            out: Dict[str, Any] | None = None

            # Ask the model for the next action
            for attempt in range(cfg.MODEL_RETRY + 1):
                out = ask_next_action(llm, objective, cfg.SCREENSHOT_PATH, trim_history(history))
                action = (out.get("action") or "NOOP").upper()

                # Done statement
                if action == "BITTI":
                    print("[MODEL] BITTI -> task completed, ending loop.")
                    break

                # Normal coordinate-based actions like CLICK
                if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                    x = float(out.get("x", 0.5))
                    y = float(out.get("y", 0.5))
                    ok, reason = validate_xy(x, y)
                    if ok:
                        break
                    print(f"[WARN] Invalid coordinates ({reason}), retrying.")
                    history.append({"action": "INVALID_COORDS", "raw": out})
                    out = None
                    continue

                # Other action types are accepted directly
                break

            # If out is None, the model could not produce a valid action
            if out is None:
                print("[ERROR] Model could not produce a valid action, ending loop for this command.")
                break

            print("[MODEL]", out)

            # Repeat guard: stop if the same action is repeated
            stop, why = should_stop_on_repeat(history, out)
            if stop:
                print(f"[STOP] {why} -> ending loop for this command.")
                break

            # If model returned BITTI (done)
            if (out.get("action") or "").upper() == "BITTI":
                print("Model says task is complete. Waiting for new command.")
                break

            # Draw preview (optional)
            action = (out.get("action") or "").upper()
            if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                preview_path = cfg.PREVIEW_PATH_TEMPLATE.format(i=step)
                draw_preview(img, float(out["x"]), float(out["y"]), preview_path)

            # Execute the action
            execute_action(sandbox, out)
            history.append(out)

            step += 1

            # Safety: stop if step count is too high
            if step > cfg.MAX_STEPS:
                print("[STOP] MAX_STEPS exceeded, ending loop for this command.")
                break

        # Loop for a single objective ends here,
        # then ask the user for a new command
        print("Ready for the next command.")


if __name__ == "__main__":
    main()
