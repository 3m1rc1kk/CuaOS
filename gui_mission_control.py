#!/usr/bin/env python3
"""
CUA Mission Control — Main Window
Professional task control interface connected to a Docker sandbox.
"""
from __future__ import annotations

import sys
import time
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QImage, QPainter, QKeyEvent, QMouseEvent, QWheelEvent, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy, QSplitter
)

from src.config import cfg
from src.sandbox import Sandbox
from src.llm_client import load_llm, ask_next_action
from src.vision import capture_screen, capture_screen_raw, draw_preview
from src.guards import validate_xy, should_stop_on_repeat
from src.actions import execute_action
from src.design_system import build_stylesheet
from src.panels import TopBar, CommandPanel, InspectorPanel, LogPanel


# ═══════════════════════════════════════════
# Agent core (taken from gui_main.py)
# ═══════════════════════════════════════════

def trim_history(history: List[Dict[str, Any]], keep_last: int = 6) -> List[Dict[str, Any]]:
    return history[-keep_last:] if len(history) > keep_last else history


def _center_from_bbox(b: List[float]) -> Tuple[float, float]:
    x1, y1, x2, y2 = map(float, b)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _extract_xy(out: Dict[str, Any]) -> Tuple[float, float]:
    x = out.get("x", 0.5)
    y = out.get("y", 0.5)
    pos = out.get("position", None)
    if pos is not None and isinstance(pos, (list, tuple)):
        if len(pos) == 2 and all(isinstance(t, (int, float)) for t in pos):
            return float(pos[0]), float(pos[1])
        if len(pos) == 4 and all(isinstance(t, (int, float)) for t in pos):
            return _center_from_bbox(list(pos))
        if len(pos) == 2 and all(isinstance(t, (list, tuple)) and len(t) == 2 for t in pos):
            (x1, y1), (x2, y2) = pos
            return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0
    if isinstance(x, (list, tuple)):
        if len(x) == 2: return float(x[0]), float(x[1])
        if len(x) == 4: return _center_from_bbox(list(x))
    if isinstance(y, (list, tuple)):
        if len(y) == 2: return float(y[0]), float(y[1])
        if len(y) == 4: return _center_from_bbox(list(y))
    return float(x), float(y)


# ═══════════════════════════════════════════
# PIL → QPixmap
# ═══════════════════════════════════════════

def pil_to_qpixmap(pil_img) -> QPixmap:
    rgb = pil_img.convert("RGB")
    w, h = rgb.size
    data = rgb.tobytes("raw", "RGB")
    bpl = 3 * w
    qimg = QImage(data, w, h, bpl, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


# ═══════════════════════════════════════════
# VMView — Live VM Screen (from gui_main.py)
# ═══════════════════════════════════════════

class VMView(QLabel):
    """Renders the VM screen with letterbox (fit) scaling and forwards mouse/keyboard input to the VM."""

    def __init__(self, sandbox: Sandbox, parent=None):
        super().__init__(parent)
        self.sandbox = sandbox
        self._pm: Optional[QPixmap] = None
        self._draw_rect: Optional[Tuple[int, int, int, int]] = None
        self.input_enabled: bool = True
        self._pressed_btn: Optional[int] = None
        self._last_move_ts: float = 0.0
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("vmView")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_frame(self, pm: QPixmap) -> None:
        self._pm = pm
        self.update()

    def _pos_to_norm(self, x: int, y: int) -> Optional[Tuple[float, float]]:
        if not self._pm or not self._draw_rect:
            return None
        dx, dy, dw, dh = self._draw_rect
        if dw <= 0 or dh <= 0:
            return None
        if x < dx or y < dy or x >= dx + dw or y >= dy + dh:
            return None
        return float((x - dx) / dw), float((y - dy) / dh)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._pm:
            p.end()
            return
        scaled = self._pm.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self._draw_rect = (x, y, scaled.width(), scaled.height())
        p.drawPixmap(x, y, scaled)
        p.end()

    def mousePressEvent(self, e: QMouseEvent):
        if not self.input_enabled: return
        self.setFocus()
        mapped = self._pos_to_norm(int(e.position().x()), int(e.position().y()))
        if not mapped: return
        nx, ny = mapped
        btn_map = {Qt.MouseButton.LeftButton: 1, Qt.MouseButton.RightButton: 3, Qt.MouseButton.MiddleButton: 2}
        btn = btn_map.get(e.button())
        if btn is None: return
        self._pressed_btn = btn
        self.sandbox.mouse_move_norm(nx, ny)
        self.sandbox.mouse_down(btn)

    def mouseMoveEvent(self, e: QMouseEvent):
        if not self.input_enabled: return
        mapped = self._pos_to_norm(int(e.position().x()), int(e.position().y()))
        if not mapped: return
        nx, ny = mapped
        now = time.monotonic()
        if (now - self._last_move_ts) < 0.03: return
        self._last_move_ts = now
        if self._pressed_btn is not None:
            self.sandbox.drag_to_norm(nx, ny, self._pressed_btn)
        else:
            self.sandbox.mouse_move_norm(nx, ny)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if not self.input_enabled or self._pressed_btn is None: return
        self.sandbox.mouse_up(self._pressed_btn)
        self._pressed_btn = None

    def wheelEvent(self, e: QWheelEvent):
        if not self.input_enabled: return
        self.sandbox.scroll(int(e.angleDelta().y()))

    def keyPressEvent(self, e: QKeyEvent):
        if not self.input_enabled: return
        if e.key() == Qt.Key.Key_F11:
            try: self.window().toggle_fullscreen()
            except: pass
            return
        mods = e.modifiers()
        txt = e.text() or ""
        if (mods & Qt.KeyboardModifier.ControlModifier) and txt and txt.isprintable():
            self.sandbox.hotkey(["ctrl", txt.lower()]); return
        if (mods & Qt.KeyboardModifier.AltModifier) and e.key() == Qt.Key.Key_Tab:
            self.sandbox.hotkey(["alt", "tab"]); return
        if txt and txt.isprintable() and len(txt) == 1:
            self.sandbox.type_text(txt); return
        special = {
            Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Tab: "tab", Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Backspace: "backspace", Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
            Qt.Key.Key_Home: "home", Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown",
            Qt.Key.Key_Space: "space",
        }
        k = special.get(e.key())
        if k:
            self.sandbox.press_key(k)


# ═══════════════════════════════════════════
# Agent Signals
# ═══════════════════════════════════════════

class AgentSignals(QObject):
    log = pyqtSignal(str, str)          # msg, level
    busy = pyqtSignal(bool)
    finished = pyqtSignal(str)
    step_update = pyqtSignal(int, str, str)   # step_num, action, detail
    action_update = pyqtSignal(dict)
    latency_update = pyqtSignal(float)


# ═══════════════════════════════════════════
# Agent Runner
# ═══════════════════════════════════════════

def run_single_command(
    sandbox: Sandbox, llm, objective: str,
    signals: AgentSignals,
    stop_event: Optional[threading.Event] = None,
) -> str:
    history: List[Dict[str, Any]] = []
    step = 1
    click_count = 0
    type_count = 0
    t0 = time.time()

    while True:
        if stop_event and stop_event.is_set():
            return "STOPPED"

        signals.log.emit(f"═══ STEP {step} ═══", "info")
        time.sleep(getattr(cfg, "WAIT_BEFORE_SCREENSHOT_SEC", 0.8))
        img = capture_screen(sandbox, cfg.SCREENSHOT_PATH)

        out: Optional[Dict[str, Any]] = None
        t_model = time.time()

        for attempt in range(getattr(cfg, "MODEL_RETRY", 2) + 1):
            out = ask_next_action(llm, objective, cfg.SCREENSHOT_PATH, trim_history(history))
            action = (out.get("action") or "NOOP").upper()
            if action == "BITTI":
                return "DONE(BITTI)"
            if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                x, y = _extract_xy(out)
                ok, reason = validate_xy(x, y)
                if ok:
                    out["x"], out["y"] = x, y
                    break
                signals.log.emit(f"[WARN] Invalid coordinates ({reason}), retrying.", "warn")
                history.append({"action": "INVALID_COORDS", "raw": out})
                out = None
                continue
            break

        latency_ms = (time.time() - t_model) * 1000
        signals.latency_update.emit(latency_ms)

        if out is None:
            return "ERROR(no valid action)"

        action = (out.get("action") or "").upper()
        detail = out.get("why_short", out.get("target", ""))
        signals.log.emit(f"[MODEL] {action}: {detail}", "model")
        signals.action_update.emit(out)
        signals.step_update.emit(step, action, str(detail))

        # Metrics
        if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
            click_count += 1
        if action == "TYPE":
            type_count += 1

        stop, why = should_stop_on_repeat(history, out)
        if stop:
            signals.log.emit(f"[STOPPED] {why}", "warn")
            return "DONE(repeat-guard)"

        if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
            preview_path = cfg.PREVIEW_PATH_TEMPLATE.format(i=step)
            draw_preview(img, float(out["x"]), float(out["y"]), preview_path)

        execute_action(sandbox, out)
        history.append(out)
        step += 1
        if step > getattr(cfg, "MAX_STEPS", 30):
            return "DONE(max-steps)"


# ═══════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════

class MissionControlWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CUA Mission Control")
        self.resize(1680, 980)
        self.setStyleSheet(build_stylesheet())

        # --- State ---
        self.sandbox: Optional[Sandbox] = None
        self.llm = None
        self.stop_event: Optional[threading.Event] = None
        self.worker_thread: Optional[threading.Thread] = None
        self._step_count = 0
        self._click_count = 0
        self._type_count = 0
        self._run_start: float = 0

        # --- Signals ---
        self.signals = AgentSignals()
        self.signals.log.connect(self._on_log)
        self.signals.busy.connect(self._on_busy)
        self.signals.finished.connect(self._on_finished)
        self.signals.step_update.connect(self._on_step)
        self.signals.action_update.connect(self._on_action)
        self.signals.latency_update.connect(self._on_latency)

        # --- Build UI ---
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Top bar
        self.top_bar = TopBar()
        root_layout.addWidget(self.top_bar)

        # Middle splitter (left | center | right)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 0)
        body_layout.setSpacing(8)

        self.cmd_panel = CommandPanel()
        self.cmd_panel.run_requested.connect(self._on_run)
        self.cmd_panel.stop_requested.connect(self._on_stop)

        center_frame = QFrame()
        center_frame.setObjectName("centerPanel")
        center_layout = QVBoxLayout(center_frame)
        center_layout.setContentsMargins(4, 4, 4, 4)

        # VMView placeholder (populated after sandbox init)
        self.vm_view_placeholder = QLabel("Connecting to sandbox…")
        self.vm_view_placeholder.setObjectName("vmView")
        self.vm_view_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vm_view_placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_layout.addWidget(self.vm_view_placeholder)
        self.vm_view: Optional[VMView] = None

        self.inspector = InspectorPanel()

        body_layout.addWidget(self.cmd_panel)
        body_layout.addWidget(center_frame, stretch=1)
        body_layout.addWidget(self.inspector)

        root_layout.addWidget(body, stretch=1)

        # Bottom log panel
        self.log_panel = LogPanel()
        log_wrap = QWidget()
        log_layout = QHBoxLayout(log_wrap)
        log_layout.setContentsMargins(10, 4, 10, 8)
        log_layout.addWidget(self.log_panel)
        root_layout.addWidget(log_wrap)

        # --- Keyboard Shortcuts ---
        QShortcut(QKeySequence("Ctrl+Return"), self, self._shortcut_run)
        QShortcut(QKeySequence("Escape"), self, self._on_stop)
        QShortcut(QKeySequence("F11"), self, self.toggle_fullscreen)
        QShortcut(QKeySequence("Ctrl+L"), self, self.log_panel.clear)

        # --- Timer for VM screenshots ---
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh_vm)
        self.refresh_timer.start(350)

        # --- Init sandbox + model in background ---
        self._center_frame = center_frame
        self._center_layout = center_layout
        self.log_panel.append("Starting up…", "info")
        threading.Thread(target=self._init_backend, daemon=True).start()

    def _init_backend(self) -> None:
        # Sandbox
        try:
            self.signals.log.emit("Starting Docker container…", "info")
            self.sandbox = Sandbox(cfg)
            self.sandbox.start()
            self.signals.log.emit("Docker sandbox connected ✓", "success")
            QTimer.singleShot(0, self._setup_vm_view)
            QTimer.singleShot(0, lambda: self.top_bar.set_docker_status(True))
            QTimer.singleShot(0, lambda: self.inspector.set_vm_info(
                cfg.SANDBOX_NAME, cfg.VNC_RESOLUTION,
                f"http://127.0.0.1:{cfg.API_PORT}"))
        except Exception as e:
            self.signals.log.emit(f"Docker ERROR: {e}", "error")
            QTimer.singleShot(0, lambda: self.top_bar.set_docker_status(False))

        # LLM
        try:
            QTimer.singleShot(0, lambda: self.top_bar.set_model_status("loading"))
            self.signals.log.emit("Loading model (Qwen3)…", "info")
            self.llm = load_llm()
            self.signals.log.emit("Model ready ✓", "success")
            QTimer.singleShot(0, lambda: self.top_bar.set_model_status("ready"))
        except Exception as e:
            self.signals.log.emit(f"Model ERROR: {e}", "error")
            QTimer.singleShot(0, lambda: self.top_bar.set_model_status("error"))

        QTimer.singleShot(0, lambda: self.inspector.set_config(cfg))

    def _setup_vm_view(self) -> None:
        if not self.sandbox:
            return
        self.vm_view = VMView(self.sandbox)
        self.vm_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._center_layout.replaceWidget(self.vm_view_placeholder, self.vm_view)
        self.vm_view_placeholder.deleteLater()
        self.vm_view_placeholder = None

    def _refresh_vm(self) -> None:
        if not self.sandbox or not self.vm_view:
            return
        try:
            img = capture_screen_raw(self.sandbox)
            pm = pil_to_qpixmap(img)
            self.vm_view.set_frame(pm)
        except Exception:
            pass

    # --- Shortcuts ---
    def _shortcut_run(self) -> None:
        text = self.cmd_panel.cmd_input.text().strip()
        if text:
            self._on_run(text)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    # --- Agent execution ---
    def _on_run(self, objective: str) -> None:
        if not objective:
            self.log_panel.append("Command cannot be empty.", "warn")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            self.log_panel.append("A command is already running.", "warn")
            return
        if not self.llm:
            self.log_panel.append("Model not loaded yet!", "error")
            return
        if not self.sandbox:
            self.log_panel.append("No sandbox connection!", "error")
            return

        # Optional translation
        translated = objective
        try:
            from transformers import MarianMTModel, MarianTokenizer
            _tn = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-tc-big-tr-en")
            _tm = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-tc-big-tr-en")
            out = _tm.generate(**_tn(objective, return_tensors="pt", padding=True))
            translated = _tn.decode(out[0], skip_special_tokens=True)
            if translated != objective:
                self.log_panel.append(f"Translation: {objective} → {translated}", "info")
        except Exception:
            pass  # translation not available, use raw text

        self._step_count = 0
        self._click_count = 0
        self._type_count = 0
        self._run_start = time.time()
        self.cmd_panel.clear_steps()
        self.stop_event = threading.Event()
        self.signals.busy.emit(True)
        self.log_panel.append(f"Command started: {translated}", "info")

        def worker():
            try:
                res = run_single_command(
                    self.sandbox, self.llm, translated,
                    self.signals, self.stop_event)
                self.signals.finished.emit(f"Result: {res}")
            except Exception:
                self.signals.log.emit("ERROR:\n" + traceback.format_exc(), "error")
            finally:
                self.signals.busy.emit(False)

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _on_stop(self) -> None:
        if self.stop_event:
            self.stop_event.set()
            self.log_panel.append("Stop signal sent.", "warn")

    # --- Signal handlers ---
    def _on_log(self, msg: str, level: str) -> None:
        self.log_panel.append(msg, level)

    def _on_busy(self, busy: bool) -> None:
        self.cmd_panel.set_busy(busy)
        if self.vm_view:
            self.vm_view.input_enabled = not busy
        self.refresh_timer.setInterval(650 if busy else 350)

    def _on_finished(self, msg: str) -> None:
        elapsed = time.time() - self._run_start
        self.log_panel.append(msg, "success")
        self.inspector.set_metrics(self._step_count, self._click_count, self._type_count, elapsed)

    def _on_step(self, step_num: int, action: str, detail: str) -> None:
        self._step_count = step_num
        if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
            self._click_count += 1
        if action == "TYPE":
            self._type_count += 1
        self.cmd_panel.add_step(step_num, action, detail)
        self.top_bar.set_step(step_num)
        elapsed = time.time() - self._run_start
        self.inspector.set_metrics(self._step_count, self._click_count, self._type_count, elapsed)

    def _on_action(self, action_dict: dict) -> None:
        self.inspector.set_last_action(action_dict)

    def _on_latency(self, ms: float) -> None:
        self.top_bar.set_latency(ms)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MissionControlWindow()
    w.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
