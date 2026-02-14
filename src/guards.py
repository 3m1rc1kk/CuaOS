# guards.py
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.config import cfg

CLICK_ACTIONS = {"CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"}


def validate_xy(x: float, y: float) -> Tuple[bool, str]:
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return False, "x/y out of [0,1]"
    if x < cfg.MIN_MARGIN or x > (1.0 - cfg.MIN_MARGIN) or y < cfg.MIN_MARGIN or y > (1.0 - cfg.MIN_MARGIN):
        return False, f"x/y too close to edge (margin={cfg.MIN_MARGIN})"
    return True, ""


def action_signature(act: Dict[str, Any]) -> str:
    a = (act.get("action") or "NOOP").upper()
    if a in CLICK_ACTIONS:
        return f"{a}:{float(act.get('x', 0)):.4f},{float(act.get('y', 0)):.4f}"
    if a == "TYPE":
        return f"TYPE:{act.get('text','')}"
    if a == "PRESS":
        return f"PRESS:{act.get('key','')}"
    if a == "HOTKEY":
        return f"HOTKEY:{','.join(act.get('keys') or [])}"
    if a == "SCROLL":
        return f"SCROLL:{int(act.get('scroll',0))}"
    if a == "WAIT":
        return f"WAIT:{float(act.get('seconds',0))}"
    return a


def _same_xy(a, b, eps: float) -> bool:
    try:
        return abs(float(a["x"]) - float(b["x"])) <= eps and abs(float(a["y"]) - float(b["y"])) <= eps
    except Exception:
        return False

def should_stop_on_repeat(history, new_action):
    # cfg.STOP_ON_REPEAT yoksa True varsay
    if not getattr(cfg, "STOP_ON_REPEAT", True):
        return False, ""

    if not history:
        return False, ""

    last = history[-1]
    a1 = (last.get("action") or "").upper()
    a2 = (new_action.get("action") or "").upper()

    # Is the action the same?
    if a1 != a2:
        return False, ""

    # TYPE recheck
    if a2 == "TYPE":
        if (last.get("text") or "") == (new_action.get("text") or ""):
            return True, "Repeat TYPE detected (same text)."

    # PRESS recheck
    if a2 == "PRESS":
        if (last.get("key") or "") == (new_action.get("key") or ""):
            return True, "Repeat PRESS detected (same key)."

    # HOTKEY recheck
    if a2 == "HOTKEY":
        if (last.get("keys") or []) == (new_action.get("keys") or []):
            return True, "Repeat HOTKEY detected (same keys)."

    # CLICK-like repeat check (same target or same coordinates)
    if a2 in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
        same_target = (last.get("target") or "") == (new_action.get("target") or "")
        eps = float(getattr(cfg, "REPEAT_XY_EPS", 0.01))
        same_xy = _same_xy(last, new_action, eps)
        if same_target or same_xy:
            return True, "Repeat pointer action detected (same target/coords)."

    return False, ""
