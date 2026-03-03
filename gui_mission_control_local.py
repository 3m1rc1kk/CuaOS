#!/usr/bin/env python3
"""
CUA Mission Control — Local-First Hierarchical Agent GUI
Plan → Execute → Verify loop with local GGUF planner support.
"""
from __future__ import annotations

import json
import sys
import time
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QImage, QPainter, QKeyEvent, QMouseEvent, QWheelEvent, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy,
    QLineEdit, QComboBox, QPushButton, QGroupBox, QFormLayout,
    QTextEdit, QSpinBox, QCheckBox,
)

from src.config import cfg
from src.sandbox import Sandbox
from src.llm_client import load_llm, ask_next_action
from src.vision import capture_screen, capture_screen_raw, draw_preview
from src.guards import validate_xy, should_stop_on_repeat
from src.actions import execute_action
from src.design_system import build_stylesheet
from src.panels import TopBar, CommandPanel, InspectorPanel, LogPanel
from src.planner import Plan, PlanStep, Planner
from src.verifier import VerifierResult


# ═══════════════════════════════════════════
# Agent helpers (from gui_main.py)
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
# VMView — Live VM Screen
# ═══════════════════════════════════════════

class VMView(QLabel):
    """Renders the VM screen with letterbox scaling and forwards mouse/keyboard input."""

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
    log = pyqtSignal(str, str)              # msg, level
    busy = pyqtSignal(bool)
    finished = pyqtSignal(str)
    step_update = pyqtSignal(int, str, str) # step_num, action, detail
    action_update = pyqtSignal(dict)
    latency_update = pyqtSignal(float)
    plan_ready = pyqtSignal(dict)           # Plan.to_dict()
    plan_step_status = pyqtSignal(str, str) # step_id, status ("running","done","failed","pending")
    verifier_result = pyqtSignal(dict)      # VerifierResult.to_dict()


# ═══════════════════════════════════════════
# Planner Settings Panel (local + API)
# ═══════════════════════════════════════════

from PyQt6.QtWidgets import QFileDialog

class PlannerSettingsPanel(QGroupBox):
    """Panel for configuring the Planner (Local GGUF or API)."""

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("🧠 Planner Settings", parent)
        self.setObjectName("plannerSettingsPanel")
        self.setStyleSheet("""
            QGroupBox {
                color: #e3f2fd;
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #1e3a5f;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 18px;
                background: #0f2744;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLabel {
                color: #90caf9;
                font-size: 12px;
            }
            QLineEdit, QComboBox, QSpinBox {
                background: #0d1f36;
                color: #e3f2fd;
                border: 1px solid #1565c0;
                border-radius: 4px;
                padding: 5px 8px;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #2196f3;
            }
            QPushButton {
                background: #1565c0;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #1976d2;
            }
            QPushButton:pressed {
                background: #0d47a1;
            }
            QPushButton#applyBtn {
                background: #2e7d32;
            }
            QPushButton#applyBtn:hover {
                background: #388e3c;
            }
            QPushButton#browseBtn {
                background: #5c6bc0;
                padding: 5px 10px;
                font-size: 11px;
            }
            QPushButton#browseBtn:hover {
                background: #7986cb;
            }
            QCheckBox {
                color: #90caf9;
                font-size: 12px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #1565c0;
                border-radius: 3px;
                background: #0d1f36;
            }
            QCheckBox::indicator:checked {
                background: #2196f3;
                border-color: #2196f3;
            }
        """)

        layout = QFormLayout(self)
        layout.setContentsMargins(12, 24, 12, 12)
        layout.setSpacing(8)

        # Provider dropdown
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["Local GGUF", "OpenRouter", "OpenAI"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_change)
        layout.addRow("Provider:", self.provider_combo)

        # ── Local GGUF: Manual file browse ──
        local_path_row = QHBoxLayout()
        self.local_path_input = QLineEdit()
        self.local_path_input.setText(cfg.PLANNER_GGUF_LOCAL_PATH)
        self.local_path_input.setPlaceholderText("/path/to/model.gguf")
        local_path_row.addWidget(self.local_path_input)
        self.browse_btn = QPushButton("📂 Browse")
        self.browse_btn.setObjectName("browseBtn")
        self.browse_btn.clicked.connect(self._on_browse)
        local_path_row.addWidget(self.browse_btn)
        local_path_widget = QWidget()
        local_path_widget.setLayout(local_path_row)
        layout.addRow("Local File:", local_path_widget)
        self._local_path_widget = local_path_widget

        # Separator label
        self.or_label = QLabel("─── or download from HuggingFace ───")
        self.or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.or_label.setStyleSheet("color: #546e7a; font-size: 10px; padding: 2px 0;")
        layout.addRow(self.or_label)

        # ── Local GGUF: HuggingFace download ──
        self.gguf_repo_input = QLineEdit()
        self.gguf_repo_input.setText(cfg.PLANNER_GGUF_REPO_ID)
        self.gguf_repo_input.setPlaceholderText("e.g. bartowski/Qwen2.5-7B-Instruct-GGUF")
        layout.addRow("HF Repo:", self.gguf_repo_input)

        self.gguf_file_input = QLineEdit()
        self.gguf_file_input.setText(cfg.PLANNER_GGUF_MODEL_FILENAME)
        self.gguf_file_input.setPlaceholderText("e.g. Qwen2.5-7B-Instruct-Q4_K_M.gguf")
        layout.addRow("HF File:", self.gguf_file_input)

        # ── GPU Layers with Auto checkbox ──
        gpu_row = QHBoxLayout()
        self.auto_gpu_checkbox = QCheckBox("Auto (Optimal)")
        self.auto_gpu_checkbox.setChecked(cfg.PLANNER_N_GPU_LAYERS == -1)
        self.auto_gpu_checkbox.stateChanged.connect(self._on_auto_gpu_toggle)
        gpu_row.addWidget(self.auto_gpu_checkbox)

        self.gpu_layers_spin = QSpinBox()
        self.gpu_layers_spin.setRange(0, 200)
        self.gpu_layers_spin.setValue(max(0, cfg.PLANNER_N_GPU_LAYERS))
        self.gpu_layers_spin.setToolTip("Manual GPU layer count (0 = CPU only)")
        self.gpu_layers_spin.setEnabled(not self.auto_gpu_checkbox.isChecked())
        gpu_row.addWidget(self.gpu_layers_spin)
        gpu_widget = QWidget()
        gpu_widget.setLayout(gpu_row)
        layout.addRow("GPU Layers:", gpu_widget)
        self._gpu_widget = gpu_widget

        # GPU info label (shows detected VRAM)
        self.gpu_info_label = QLabel("")
        self.gpu_info_label.setStyleSheet("color: #546e7a; font-size: 10px;")
        layout.addRow(self.gpu_info_label)
        self._detect_gpu_info()

        # ── API fields ──
        self.model_input = QLineEdit()
        self.model_input.setText(cfg.PLANNER_MODEL)
        self.model_input.setPlaceholderText("e.g. meta-llama/llama-3.3-70b-instruct:free")
        layout.addRow("Model:", self.model_input)

        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setPlaceholderText("Enter your API key...")
        self.api_key_input.setText(cfg.PLANNER_API_KEY)
        layout.addRow("API Key:", self.api_key_input)

        # Apply button
        self.apply_btn = QPushButton("✅ Apply & Load Planner")
        self.apply_btn.setObjectName("applyBtn")
        self.apply_btn.clicked.connect(self._on_apply)
        layout.addRow(self.apply_btn)

        # Status label
        self.status_label = QLabel("⚪ Not configured")
        self.status_label.setObjectName("plannerStatus")
        self.status_label.setWordWrap(True)
        layout.addRow(self.status_label)

        self.setFixedWidth(340)

        # Set initial field visibility
        self._on_provider_change(0)

    def _on_browse(self):
        """Open file dialog to select a local .gguf model file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GGUF Model File",
            "",
            "GGUF Models (*.gguf);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if path:
            self.local_path_input.setText(path)
            # Auto-detect file size and show info
            try:
                import os
                size_mb = os.path.getsize(path) / (1024 * 1024)
                name = os.path.basename(path)
                self.status_label.setText(
                    f"📁 {name}\n({size_mb:.0f} MB)")
            except Exception:
                pass

    def _on_auto_gpu_toggle(self, state):
        """Enable/disable manual GPU layer spinner."""
        auto = state == Qt.CheckState.Checked.value
        self.gpu_layers_spin.setEnabled(not auto)
        if auto:
            self.gpu_layers_spin.setToolTip("Auto mode: GPU layers will be calculated at load time")
        else:
            self.gpu_layers_spin.setToolTip("Manual GPU layer count (0 = CPU only)")

    def _detect_gpu_info(self):
        """Detect GPU VRAM and show info label (non-blocking)."""
        def detect():
            try:
                import subprocess
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    lines = result.stdout.strip().split("\n")
                    parts = lines[0].split(",")
                    if len(parts) >= 3:
                        name = parts[0].strip()
                        total = int(parts[1].strip())
                        free = int(parts[2].strip())
                        info = f"🖥 {name} — {free}/{total} MB VRAM free"
                        QTimer.singleShot(0, lambda: self.gpu_info_label.setText(info))
                        return
                QTimer.singleShot(0, lambda: self.gpu_info_label.setText(
                    "⚠ No NVIDIA GPU detected (CPU only)"))
            except FileNotFoundError:
                QTimer.singleShot(0, lambda: self.gpu_info_label.setText(
                    "⚠ nvidia-smi not found (CPU only)"))
            except Exception:
                QTimer.singleShot(0, lambda: self.gpu_info_label.setText(
                    "⚠ GPU detection failed"))

        threading.Thread(target=detect, daemon=True).start()

    def _on_provider_change(self, idx: int):
        is_local = idx == 0
        # Local fields
        self._local_path_widget.setVisible(is_local)
        self.or_label.setVisible(is_local)
        self.gguf_repo_input.setVisible(is_local)
        self.gguf_file_input.setVisible(is_local)
        self._gpu_widget.setVisible(is_local)
        self.gpu_info_label.setVisible(is_local)
        # API fields
        self.model_input.setVisible(not is_local)
        self.api_key_input.setVisible(not is_local)

        # Find and toggle label visibility
        form = self.layout()
        if isinstance(form, QFormLayout):
            local_labels = ("Local File:", "HF Repo:", "HF File:", "GPU Layers:")
            api_labels = ("Model:", "API Key:")
            for row in range(form.rowCount()):
                label_item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
                field_item = form.itemAt(row, QFormLayout.ItemRole.FieldRole)
                if not label_item or not field_item:
                    continue
                label = label_item.widget()
                if not label:
                    continue
                label_text = label.text() if hasattr(label, 'text') else ""
                if label_text in local_labels:
                    label.setVisible(is_local)
                elif label_text in api_labels:
                    label.setVisible(not is_local)

    def _on_apply(self):
        self._apply_to_config()
        self.settings_changed.emit()
        self.status_label.setText("🟡 Loading planner...")

    def _apply_to_config(self):
        """Write UI values back to cfg for the planner."""
        idx = self.provider_combo.currentIndex()
        provider_map = {0: "local", 1: "openrouter", 2: "openai"}
        cfg.PLANNER_PROVIDER = provider_map.get(idx, "local")

        if idx == 0:
            cfg.PLANNER_GGUF_LOCAL_PATH = self.local_path_input.text().strip()
            cfg.PLANNER_GGUF_REPO_ID = self.gguf_repo_input.text().strip()
            cfg.PLANNER_GGUF_MODEL_FILENAME = self.gguf_file_input.text().strip()
            if self.auto_gpu_checkbox.isChecked():
                cfg.PLANNER_N_GPU_LAYERS = -1  # Auto
            else:
                cfg.PLANNER_N_GPU_LAYERS = self.gpu_layers_spin.value()
        else:
            cfg.PLANNER_MODEL = self.model_input.text().strip()
            cfg.PLANNER_API_KEY = self.api_key_input.text().strip()

    def set_status(self, text: str):
        self.status_label.setText(text)


# ═══════════════════════════════════════════
# Hierarchical Plan Display Widget
# ═══════════════════════════════════════════

class HierarchicalPlanDisplay(QFrame):
    """Shows the generated Plan with structured steps, status, and verifier results."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("planDisplay")
        self.setStyleSheet("""
            QFrame#planDisplay {
                background: #0a1929;
                border: 1px solid #1e3a5f;
                border-radius: 6px;
            }
            QLabel#planTitle {
                color: #64b5f6;
                font-weight: bold;
                font-size: 13px;
            }
            QTextEdit {
                background: transparent;
                color: #e3f2fd;
                border: none;
                font-size: 12px;
                font-family: 'Fira Code', 'Consolas', monospace;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self.title = QLabel("📋 Hierarchical Plan")
        self.title.setObjectName("planTitle")
        layout.addWidget(self.title)

        self.plan_text = QTextEdit()
        self.plan_text.setReadOnly(True)
        self.plan_text.setMaximumHeight(200)
        layout.addWidget(self.plan_text)

        self._plan: Optional[Plan] = None
        self._step_statuses: Dict[str, str] = {}  # step_id -> "pending"|"running"|"done"|"failed"
        self._verifier_results: Dict[str, VerifierResult] = {}

    def set_plan(self, plan_dict: Dict[str, Any]):
        """Display the plan from a dict."""
        self._plan = Plan.from_dict(plan_dict)
        self._step_statuses = {s.id: "pending" for s in self._plan.steps}
        self._verifier_results = {}
        self._render()

    def set_step_status(self, step_id: str, status: str):
        self._step_statuses[step_id] = status
        self._render()

    def set_verifier_result(self, vr_dict: Dict[str, Any]):
        vr = VerifierResult.from_dict(vr_dict)
        self._verifier_results[vr.step_id] = vr
        self._render()

    def _render(self):
        if not self._plan:
            self.plan_text.setHtml("<i style='color:#546e7a'>No plan generated yet</i>")
            return

        lines = []
        lines.append(
            f"<span style='color:#90caf9'>"
            f"<b>Objective:</b> {self._plan.objective} "
            f"<span style='color:#546e7a'>(confidence: {self._plan.confidence:.0%})</span>"
            f"</span>"
        )
        lines.append("")

        for step in self._plan.steps:
            status = self._step_statuses.get(step.id, "pending")
            icon_map = {
                "pending": "⬜", "running": "▶️",
                "done": "✅", "failed": "❌"
            }
            color_map = {
                "pending": "#546e7a", "running": "#ffb74d",
                "done": "#4caf50", "failed": "#f44336"
            }
            icon = icon_map.get(status, "⬜")
            color = color_map.get(status, "#546e7a")

            criteria_str = " · ".join(step.success_criteria) if step.success_criteria else ""

            line = (
                f"<span style='color:{color}'>"
                f"{icon} <b>{step.id}.</b> "
                f"<span style='color:#64b5f6'>{step.title}</span>"
            )

            if criteria_str:
                line += f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;<span style='color:#546e7a;font-size:10px'>✓ {criteria_str}</span>"

            # Show verifier result if available
            vr = self._verifier_results.get(step.id)
            if vr:
                vr_color = "#4caf50" if vr.done else "#ff9800"
                evidence_str = "; ".join(vr.evidence[:2]) if vr.evidence else ""
                line += (
                    f"<br/>&nbsp;&nbsp;&nbsp;&nbsp;"
                    f"<span style='color:{vr_color};font-size:10px'>"
                    f"🔍 {evidence_str} ({vr.confidence:.0%})"
                    f"</span>"
                )

            line += "</span>"
            lines.append(line)

        self.plan_text.setHtml("<br>".join(lines))

    def clear(self):
        self._plan = None
        self._step_statuses = {}
        self._verifier_results = {}
        self.plan_text.clear()


# ═══════════════════════════════════════════
# Direct runner (no planner — backward compat)
# ═══════════════════════════════════════════

def run_single_command(
    sandbox: Sandbox, llm, objective: str,
    signals: AgentSignals,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """Original single-command runner for no-planner mode."""
    history: List[Dict[str, Any]] = []
    step = 1

    while True:
        if stop_event and stop_event.is_set():
            return "STOPPED"

        signals.log.emit(f"═══ STEP {step} ═══", "info")
        time.sleep(getattr(cfg, "WAIT_BEFORE_SCREENSHOT_SEC", 0.2))
        img = capture_screen(sandbox, cfg.SCREENSHOT_PATH)

        out: Optional[Dict[str, Any]] = None

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

        if out is None:
            return "ERROR(no valid action)"

        action = (out.get("action") or "").upper()
        detail = out.get("why_short", out.get("target", ""))
        signals.log.emit(f"[MODEL] {action}: {detail}", "model")
        signals.action_update.emit(out)
        signals.step_update.emit(step, action, str(detail))

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
# GUI-integrated hierarchical agent loop
# ═══════════════════════════════════════════

def _build_executor_objective(original_objective: str, step: PlanStep, verifier_hint: str = "") -> str:
    """Build enriched objective for executor."""
    criteria_str = "; ".join(step.success_criteria)
    parts = [
        f"OVERALL OBJECTIVE: {original_objective}",
        f"CURRENT_STEP: {step.title}",
        f"SUCCESS_CRITERIA: {criteria_str}",
    ]
    if step.executor_hint:
        preferred = step.executor_hint.get("preferred_actions", [])
        if preferred:
            parts.append(f"PREFERRED_ACTIONS: {', '.join(preferred)}")
    if verifier_hint:
        parts.append(f"PREVIOUS_ATTEMPT_FEEDBACK: {verifier_hint}")
    parts.append("Execute the CURRENT_STEP. Output ONLY one JSON action.")
    return "\n".join(parts)


def run_hierarchical_loop(
    sandbox: Sandbox,
    llm,
    planner: Planner,
    objective: str,
    signals: AgentSignals,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """
    GUI-integrated hierarchical agent loop with plan → execute → verify.
    Sends live signals to the GUI for plan display, step status, and verifier results.
    """
    from src.verifier import verify_step

    max_replan = getattr(cfg, "PLANNER_MAX_REPLAN", 2)
    global_step_count = 0
    replan_count = 0
    context = ""

    while replan_count <= max_replan:
        if stop_event and stop_event.is_set():
            return "STOPPED"

        # ── Generate plan ─────────────────────────────────────
        action_word = "Generating" if replan_count == 0 else "Re-generating"
        signals.log.emit(f"🧠 {action_word} plan (attempt {replan_count + 1})...", "info")

        try:
            plan = planner.plan(objective, context)
        except Exception as e:
            signals.log.emit(f"❌ Plan generation failed: {e}", "error")
            return f"ERROR(planner_failed)"

        signals.log.emit(
            f"📋 Plan generated (confidence={plan.confidence:.0%}, "
            f"steps={len(plan.steps)})", "success")
        signals.plan_ready.emit(plan.to_dict())

        # Log plan details
        for s in plan.steps:
            signals.log.emit(f"  {s.id}. {s.title} → [{'; '.join(s.success_criteria)}]", "info")

        # ── Execute plan ──────────────────────────────────────
        history: List[Dict[str, Any]] = []
        plan_completed = True

        for step_idx, step in enumerate(plan.steps):
            if stop_event and stop_event.is_set():
                return "STOPPED"

            signals.log.emit(f"\n{'─'*40}", "info")
            signals.log.emit(f"▶ [{step.id}] {step.title}", "info")
            signals.plan_step_status.emit(step.id, "running")

            attempts = 0
            verifier_hint = ""
            step_done = False

            while attempts < step.max_attempts:
                if stop_event and stop_event.is_set():
                    return "STOPPED"

                attempts += 1
                global_step_count += 1

                if global_step_count > cfg.MAX_STEPS:
                    signals.log.emit(f"⚠ MAX_STEPS ({cfg.MAX_STEPS}) exceeded.", "warn")
                    return "DONE(max_steps)"

                signals.log.emit(
                    f"  Attempt {attempts}/{step.max_attempts} "
                    f"(action #{global_step_count})", "info")

                # 1. Screenshot
                time.sleep(cfg.WAIT_BEFORE_SCREENSHOT_SEC)
                img = capture_screen(sandbox, cfg.SCREENSHOT_PATH)

                # 2. Ask executor
                enriched = _build_executor_objective(objective, step, verifier_hint)
                out: Optional[Dict[str, Any]] = None

                for retry in range(cfg.MODEL_RETRY + 1):
                    out = ask_next_action(
                        llm, enriched, cfg.SCREENSHOT_PATH, trim_history(history))
                    action = (out.get("action") or "NOOP").upper()

                    if action == "BITTI":
                        step_done = True
                        break

                    if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                        x, y = _extract_xy(out)
                        ok, reason = validate_xy(x, y)
                        if ok:
                            out["x"], out["y"] = x, y
                            break
                        signals.log.emit(f"  ⚠ Invalid coords ({reason}), retrying...", "warn")
                        history.append({"action": "INVALID_COORDS", "raw": out})
                        out = None
                        continue
                    break

                if step_done:
                    signals.log.emit(f"  ✓ [{step.id}] Executor says done (BITTI)", "success")
                    signals.plan_step_status.emit(step.id, "done")
                    break

                if out is None:
                    verifier_hint = "Executor failed. Try a different approach."
                    continue

                action = (out.get("action") or "").upper()
                detail = out.get("why_short", out.get("target", ""))
                signals.log.emit(f"  [EXEC] {action}: {detail}", "model")
                signals.action_update.emit(out)
                signals.step_update.emit(global_step_count, action, str(detail))

                # 3. Repeat guard
                stop, why = should_stop_on_repeat(history, out)
                if stop:
                    signals.log.emit(f"  [GUARD] {why}", "warn")
                    verifier_hint = f"Repeat blocked: {why}. Try something different."
                    continue

                # 4. Preview
                if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                    preview_path = cfg.PREVIEW_PATH_TEMPLATE.format(i=global_step_count)
                    draw_preview(img, float(out["x"]), float(out["y"]), preview_path)

                # 5. Execute
                execute_action(sandbox, out)
                history.append(out)

                # 6. Post-action screenshot
                time.sleep(cfg.WAIT_BEFORE_SCREENSHOT_SEC)
                capture_screen(sandbox, cfg.SCREENSHOT_PATH)

                # 7. Verify
                signals.log.emit(f"  🔍 Verifying...", "info")
                try:
                    vr = verify_step(llm, step, cfg.SCREENSHOT_PATH)
                except Exception as e:
                    signals.log.emit(f"  ⚠ Verifier error: {e}", "warn")
                    vr = VerifierResult(
                        step_id=step.id, done=False,
                        evidence=[f"verifier error: {e}"],
                        failure_type="OTHER",
                        suggested_fix="retry",
                        confidence=0.1,
                    )

                signals.verifier_result.emit(vr.to_dict())
                evidence_str = "; ".join(vr.evidence[:2]) if vr.evidence else ""
                signals.log.emit(
                    f"  🔍 done={vr.done} confidence={vr.confidence:.0%} "
                    f"| {evidence_str}", "info")

                if vr.done:
                    signals.log.emit(f"  ✓ [{step.id}] Verified!", "success")
                    signals.plan_step_status.emit(step.id, "done")
                    step_done = True
                    break
                else:
                    verifier_hint = (
                        f"Not satisfied. Failure: {vr.failure_type}. "
                        f"Fix: {vr.suggested_fix}. Evidence: {evidence_str}"
                    )
                    signals.log.emit(f"  ✗ [{step.id}] {verifier_hint}", "warn")

            if not step_done:
                signals.log.emit(
                    f"  ❌ [{step.id}] Failed after {step.max_attempts} attempts.", "error")
                signals.plan_step_status.emit(step.id, "failed")
                plan_completed = False

                # Trigger replan
                replan_count += 1
                context = (
                    f"Previous plan got stuck at step: {step.title}. "
                    f"Failure: {verifier_hint}. "
                    f"Actions so far: {global_step_count}."
                )
                signals.log.emit(f"🔄 Replanning... ({replan_count}/{max_replan})", "warn")
                break  # Break out of step loop to replan

        if plan_completed:
            signals.log.emit(f"\n✅ Objective completed!", "success")
            return "DONE"

    signals.log.emit(f"❌ Max replans ({max_replan}) exhausted.", "error")
    return "ERROR(max_replans)"


# ═══════════════════════════════════════════
# MAIN WINDOW
# ═══════════════════════════════════════════

class MissionControlLocalWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CUA Mission Control — Hierarchical Agent (Local-First)")
        self.resize(1680, 980)
        self.setStyleSheet(build_stylesheet())

        # --- State ---
        self.sandbox: Optional[Sandbox] = None
        self.llm = None
        self.planner: Optional[Planner] = None
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
        self.signals.plan_ready.connect(self._on_plan_ready)
        self.signals.plan_step_status.connect(self._on_plan_step_status)
        self.signals.verifier_result.connect(self._on_verifier_result)

        # --- Build UI ---
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Top bar
        self.top_bar = TopBar()
        root_layout.addWidget(self.top_bar)

        # Middle: left | center | right
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(10, 8, 10, 0)
        body_layout.setSpacing(8)

        # LEFT COLUMN: Command panel + Plan display
        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        self.cmd_panel = CommandPanel()
        self.cmd_panel.run_requested.connect(self._on_run)
        self.cmd_panel.stop_requested.connect(self._on_stop)
        left_layout.addWidget(self.cmd_panel)

        self.plan_display = HierarchicalPlanDisplay()
        left_layout.addWidget(self.plan_display)

        # CENTER: VM view
        center_frame = QFrame()
        center_frame.setObjectName("centerPanel")
        center_layout = QVBoxLayout(center_frame)
        center_layout.setContentsMargins(4, 4, 4, 4)

        self.vm_view_placeholder = QLabel("Connecting to sandbox…")
        self.vm_view_placeholder.setObjectName("vmView")
        self.vm_view_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vm_view_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        center_layout.addWidget(self.vm_view_placeholder)
        self.vm_view: Optional[VMView] = None

        # RIGHT COLUMN: Inspector + Planner Settings
        right_col = QWidget()
        right_layout = QVBoxLayout(right_col)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.inspector = InspectorPanel()
        right_layout.addWidget(self.inspector)

        self.planner_settings = PlannerSettingsPanel()
        self.planner_settings.settings_changed.connect(self._on_settings_changed)
        right_layout.addWidget(self.planner_settings)

        body_layout.addWidget(left_col)
        body_layout.addWidget(center_frame, stretch=1)
        body_layout.addWidget(right_col)

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
        self.log_panel.append("Starting up… (Hierarchical Agent — Local-First)", "info")
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

        # LLM (Qwen3-VL executor + verifier)
        try:
            QTimer.singleShot(0, lambda: self.top_bar.set_model_status("loading"))
            self.signals.log.emit("Loading Qwen3-VL model (executor/verifier)…", "info")
            self.llm = load_llm()
            self.signals.log.emit("Qwen3-VL model ready ✓", "success")
            QTimer.singleShot(0, lambda: self.top_bar.set_model_status("ready"))
        except Exception as e:
            self.signals.log.emit(f"Model ERROR: {e}", "error")
            QTimer.singleShot(0, lambda: self.top_bar.set_model_status("error"))

        QTimer.singleShot(0, lambda: self.inspector.set_config(cfg))

    def _setup_vm_view(self) -> None:
        if not self.sandbox:
            return
        self.vm_view = VMView(self.sandbox)
        self.vm_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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

    # --- Settings ---
    def _on_settings_changed(self) -> None:
        """Load the planner in a background thread after settings are applied."""
        def load_planner():
            try:
                provider = cfg.PLANNER_PROVIDER.lower()
                if provider == "local":
                    from src.planner_local import LocalGGUFPlanner
                    self.planner = LocalGGUFPlanner()
                elif provider in ("openrouter", "openai"):
                    from src.planner_api import APIPlanner
                    self.planner = APIPlanner()
                else:
                    self.planner = None
                    QTimer.singleShot(0, lambda: self.planner_settings.set_status(
                        f"🔴 Unknown provider: {provider}"))
                    return

                QTimer.singleShot(0, lambda: self.planner_settings.set_status(
                    "🟢 Planner loaded!"))
                self.signals.log.emit(
                    f"✓ Planner ready (provider={provider})", "success")
            except Exception as e:
                self.planner = None
                err = str(e)[:100]
                QTimer.singleShot(0, lambda: self.planner_settings.set_status(
                    f"🔴 {err}"))
                self.signals.log.emit(f"❌ Planner load failed: {e}", "error")

        threading.Thread(target=load_planner, daemon=True).start()

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
            self.log_panel.append("Qwen3-VL model not loaded yet!", "error")
            return
        if not self.sandbox:
            self.log_panel.append("No sandbox connection!", "error")
            return

        self._step_count = 0
        self._click_count = 0
        self._type_count = 0
        self._run_start = time.time()
        self.cmd_panel.clear_steps()
        self.plan_display.clear()
        self.stop_event = threading.Event()
        self.signals.busy.emit(True)

        if self.planner is not None:
            self.log_panel.append(
                f"🧠 Hierarchical mode: \"{objective}\"", "info")
            self._run_hierarchical(objective)
        else:
            self.log_panel.append(
                f"▶ Direct mode (no planner): \"{objective}\"", "info")
            self._run_direct(objective)

    def _run_hierarchical(self, objective: str) -> None:
        """Run the full Plan→Execute→Verify loop."""
        def worker():
            try:
                res = run_hierarchical_loop(
                    sandbox=self.sandbox,
                    llm=self.llm,
                    planner=self.planner,
                    objective=objective,
                    signals=self.signals,
                    stop_event=self.stop_event,
                )
                self.signals.finished.emit(f"Result: {res}")
            except Exception:
                self.signals.log.emit(
                    "ERROR:\n" + traceback.format_exc(), "error")
            finally:
                self.signals.busy.emit(False)

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _run_direct(self, objective: str) -> None:
        """Original direct execution (no planner)."""
        def worker():
            try:
                res = run_single_command(
                    self.sandbox, self.llm, objective,
                    self.signals, self.stop_event)
                self.signals.finished.emit(f"Result: {res}")
            except Exception:
                self.signals.log.emit(
                    "ERROR:\n" + traceback.format_exc(), "error")
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
        self.inspector.set_metrics(
            self._step_count, self._click_count, self._type_count, elapsed)

    def _on_step(self, step_num: int, action: str, detail: str) -> None:
        self._step_count = step_num
        if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
            self._click_count += 1
        if action == "TYPE":
            self._type_count += 1
        self.cmd_panel.add_step(step_num, action, detail)
        self.top_bar.set_step(step_num)
        elapsed = time.time() - self._run_start
        self.inspector.set_metrics(
            self._step_count, self._click_count, self._type_count, elapsed)

    def _on_action(self, action_dict: dict) -> None:
        self.inspector.set_last_action(action_dict)

    def _on_latency(self, ms: float) -> None:
        self.top_bar.set_latency(ms)

    def _on_plan_ready(self, plan_dict: dict) -> None:
        self.plan_display.set_plan(plan_dict)

    def _on_plan_step_status(self, step_id: str, status: str) -> None:
        self.plan_display.set_step_status(step_id, status)

    def _on_verifier_result(self, vr_dict: dict) -> None:
        self.plan_display.set_verifier_result(vr_dict)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MissionControlLocalWindow()
    w.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
