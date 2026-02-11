# actions.py
from __future__ import annotations

import time
from typing import Any, Dict

from src.sandbox import Sandbox
from src.config import cfg


def _pause_after_action() -> None:
    time.sleep(getattr(cfg, "PAUSE_AFTER_ACTION_SEC", getattr(cfg, "PAUSE_AFTER_CLICK_SEC", 0.25)))


def execute_action(sandbox: Sandbox, act: Dict[str, Any]) -> None:
    """Execute one action dict produced by the model."""
    a = (act.get("action") or "NOOP").upper()

    if a == "NOOP":
        return

    if a == "WAIT":
        secs = float(act.get("seconds") or 0.5)
        time.sleep(max(0.0, min(30.0, secs)))
        return

    if a == "CLICK":
        sandbox.left_click_norm(float(act["x"]), float(act["y"]))
        _pause_after_action()
        return

    if a == "DOUBLE_CLICK":
        sandbox.double_click_norm(float(act["x"]), float(act["y"]))
        _pause_after_action()
        return

    if a == "RIGHT_CLICK":
        sandbox.right_click_norm(float(act["x"]), float(act["y"]))
        _pause_after_action()
        return

    if a == "TYPE":
        sandbox.type_text(str(act.get("text") or ""))
        _pause_after_action()
        return

    if a == "PRESS":
        sandbox.press_key(str(act.get("key") or ""))
        _pause_after_action()
        return

    if a == "HOTKEY":
        keys = act.get("keys") or []
        sandbox.hotkey([str(k) for k in keys])
        _pause_after_action()
        return

    if a == "SCROLL":
        amount = act.get("scroll")
        if amount is None:
            amount = act.get("amount", 0)
        sandbox.scroll(int(amount or 0))
        _pause_after_action()
        return

    # Optional actions (manual / advanced)
    if a == "MOVE":
        sandbox.mouse_move_norm(float(act.get("x", 0.5)), float(act.get("y", 0.5)))
        return

    if a == "MOUSE_DOWN":
        sandbox.mouse_down(int(act.get("button", 1)))
        return

    if a == "MOUSE_UP":
        sandbox.mouse_up(int(act.get("button", 1)))
        return

    if a == "DRAG_TO":
        sandbox.drag_to_norm(
            float(act.get("x", 0.5)),
            float(act.get("y", 0.5)),
            int(act.get("button", 1)),
        )
        return

    if a == "BITTI":
        return

    raise ValueError(f"Unknown action: {a} (act={act})")
