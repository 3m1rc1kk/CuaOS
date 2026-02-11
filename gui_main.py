#!/usr/bin/env python3

from __future__ import annotations

import sys
import time
import threading
import traceback
from typing import Any, Dict, List, Optional, Callable, Tuple

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QPixmap, QImage, QPainter, QKeyEvent, QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QTextEdit, QGridLayout, QFrame, QSizePolicy
)

from src.config import cfg
from src.sandbox import Sandbox
from src.llm_client import load_llm, ask_next_action
from src.vision import capture_screen, capture_screen_raw, draw_preview
from src.guards import validate_xy, should_stop_on_repeat
from src.actions import execute_action
from transformers import MarianMTModel, MarianTokenizer


model_name = "Helsinki-NLP/opus-mt-tc-big-tr-en"
tokenizer = MarianTokenizer.from_pretrained(model_name)
model = MarianMTModel.from_pretrained(model_name)

# ----------------------------
# Agent core (GUI içinde, main.py'ye ihtiyaç yok)
# ----------------------------
def trim_history(history: List[Dict[str, Any]], keep_last: int = 6) -> List[Dict[str, Any]]:
    if len(history) <= keep_last:
        return history
    return history[-keep_last:]


def _center_from_bbox(b: List[float]) -> Tuple[float, float]:
    # bbox: [x1,y1,x2,y2] (normalized)
    x1, y1, x2, y2 = map(float, b)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _extract_xy(out: Dict[str, Any]) -> Tuple[float, float]:
    """
    Model bazen x/y yerine liste döndürebiliyor (ör. bbox).
    Bu fonksiyon sağlam şekilde float (x,y) üretir.
    """
    x = out.get("x", 0.5)
    y = out.get("y", 0.5)

    # Bazı modeller "position" ya da bbox benzeri alan döndürebiliyor
    pos = out.get("position", None)
    if pos is not None:
        # [[x1,y1],[x2,y2]] veya [x1,y1,x2,y2] veya [x,y]
        if isinstance(pos, (list, tuple)):
            if len(pos) == 2 and all(isinstance(t, (int, float)) for t in pos):
                return float(pos[0]), float(pos[1])
            if len(pos) == 4 and all(isinstance(t, (int, float)) for t in pos):
                return _center_from_bbox(list(pos))
            if len(pos) == 2 and all(isinstance(t, (list, tuple)) and len(t) == 2 for t in pos):
                (x1, y1), (x2, y2) = pos
                return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0

    # x bazen [x,y] veya [x1,y1,x2,y2] gelebiliyor
    if isinstance(x, (list, tuple)):
        if len(x) == 2 and all(isinstance(t, (int, float)) for t in x):
            return float(x[0]), float(x[1])
        if len(x) == 4 and all(isinstance(t, (int, float)) for t in x):
            return _center_from_bbox(list(x))

    # y de bazen list olabilir (nadiren)
    if isinstance(y, (list, tuple)):
        if len(y) == 2 and all(isinstance(t, (int, float)) for t in y):
            return float(y[0]), float(y[1])
        if len(y) == 4 and all(isinstance(t, (int, float)) for t in y):
            return _center_from_bbox(list(y))

    return float(x), float(y)


def run_single_command(
    sandbox: Sandbox,
    llm,
    objective: str,
    log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """
    Terminaldeki main.py davranışının GUI içindeki karşılığı.
    """
    def _log(msg: str):
        if log:
            log(msg)

    history: List[Dict[str, Any]] = []
    step = 1

    while True:
        if stop_event and stop_event.is_set():
            return "STOPPED"

        _log(f"\n==================== STEP {step} ====================")

        time.sleep(getattr(cfg, "WAIT_BEFORE_SCREENSHOT_SEC", 0.8))

        img = capture_screen(sandbox, cfg.SCREENSHOT_PATH)

        out: Dict[str, Any] | None = None

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
                _log(f"[WARN] Uygun olmayan koordinat ({reason}), yeniden deneniyor.")
                history.append({"action": "INVALID_COORDS", "raw": out})
                out = None
                continue

            # diğer aksiyon türleri (TYPE/PRESS/HOTKEY/SCROLL/WAIT/NOOP) kabul
            break

        if out is None:
            return "ERROR(no valid action)"

        _log("[MODEL] " + str(out))

        stop, why = should_stop_on_repeat(history, out)
        if stop:
            _log(f"[STOP] {why}")
            return "DONE(repeat-guard)"

        action = (out.get("action") or "").upper()
        if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
            preview_path = cfg.PREVIEW_PATH_TEMPLATE.format(i=step)
            draw_preview(img, float(out["x"]), float(out["y"]), preview_path)

        execute_action(sandbox, out)
        history.append(out)

        step += 1
        if step > getattr(cfg, "MAX_STEPS", 30):
            return "DONE(max-steps)"


# ----------------------------
# Qt helpers (bozulma fix)
# ----------------------------
def pil_to_qpixmap(pil_img) -> QPixmap:
    """
    QImage raw buffer bozulmalarını engellemek için:
    - stride (bytesPerLine) veriyoruz
    - qimg.copy() ile detach ediyoruz (buffer ömrü problemi biter)
    :contentReference[oaicite:1]{index=1}
    """
    rgb = pil_img.convert("RGB")
    w, h = rgb.size
    data = rgb.tobytes("raw", "RGB")
    bytes_per_line = 3 * w
    qimg = QImage(data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def scale_crop_to_label(pm: QPixmap, label_w: int, label_h: int) -> QPixmap:
    """
    Boşluk kalmasın diye:
    - KeepAspectRatioByExpanding ile doldur
    - ortadan crop et
    """
    if label_w <= 0 or label_h <= 0:
        return pm

    scaled = pm.scaled(
        label_w, label_h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - label_w) // 2)
    y = max(0, (scaled.height() - label_h) // 2)
    return scaled.copy(x, y, label_w, label_h)




class VMView(QLabel):
    """VM ekranını letterbox (fit) çizip mouse/klavye inputunu VM'ye aktarır."""

    def __init__(self, sandbox: Sandbox, parent=None):
        super().__init__(parent)
        self.sandbox = sandbox
        self._pm: Optional[QPixmap] = None
        self._draw_rect: Optional[Tuple[int, int, int, int]] = None  # x,y,w,h
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
        nx = (x - dx) / dw
        ny = (y - dy) / dh
        return float(nx), float(ny)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)

        if not self._pm:
            p.end()
            return

        scaled = self._pm.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self._draw_rect = (x, y, scaled.width(), scaled.height())
        p.drawPixmap(x, y, scaled)
        p.end()

    def mousePressEvent(self, e: QMouseEvent):
        if not self.input_enabled:
            return
        self.setFocus()

        mapped = self._pos_to_norm(int(e.position().x()), int(e.position().y()))
        if not mapped:
            return
        nx, ny = mapped

        if e.button() == Qt.MouseButton.LeftButton:
            btn = 1
        elif e.button() == Qt.MouseButton.RightButton:
            btn = 3
        elif e.button() == Qt.MouseButton.MiddleButton:
            btn = 2
        else:
            return

        self._pressed_btn = btn
        self.sandbox.mouse_move_norm(nx, ny)
        self.sandbox.mouse_down(btn)

    def mouseMoveEvent(self, e: QMouseEvent):
        if not self.input_enabled:
            return

        mapped = self._pos_to_norm(int(e.position().x()), int(e.position().y()))
        if not mapped:
            return
        nx, ny = mapped

        now = time.monotonic()
        if (now - self._last_move_ts) < 0.03:
            return
        self._last_move_ts = now

        if self._pressed_btn is not None:
            self.sandbox.drag_to_norm(nx, ny, self._pressed_btn)
        else:
            self.sandbox.mouse_move_norm(nx, ny)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if not self.input_enabled:
            return
        if self._pressed_btn is None:
            return
        btn = self._pressed_btn
        self._pressed_btn = None
        self.sandbox.mouse_up(btn)

    def wheelEvent(self, e: QWheelEvent):
        if not self.input_enabled:
            return
        self.sandbox.scroll(int(e.angleDelta().y()))

    def keyPressEvent(self, e: QKeyEvent):
        if not self.input_enabled:
            return

        if e.key() == Qt.Key.Key_F11:
            try:
                self.window().toggle_fullscreen()
            except Exception:
                pass
            return

        mods = e.modifiers()
        txt = (e.text() or "")

        if (mods & Qt.KeyboardModifier.ControlModifier) and txt and txt.isprintable():
            self.sandbox.hotkey(["ctrl", txt.lower()])
            return

        if (mods & Qt.KeyboardModifier.AltModifier) and e.key() == Qt.Key.Key_Tab:
            self.sandbox.hotkey(["alt", "tab"])
            return

        if txt and txt.isprintable() and len(txt) == 1:
            self.sandbox.type_text(txt)
            return

        special = {
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "pageup",
            Qt.Key.Key_PageDown: "pagedown",
            Qt.Key.Key_Space: "space",
        }
        k = special.get(e.key())
        if k:
            self.sandbox.press_key(k)

# ----------------------------
# GUI
# ----------------------------
class AgentSignals(QObject):
    log = pyqtSignal(str)
    busy = pyqtSignal(bool)
    finished = pyqtSignal(str)


class AgentWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CUA VM Agent")
        self.resize(1680, 980)
        self.setStyleSheet(self._style_sheet())

        self.sandbox = Sandbox(cfg)
        self.sandbox.start()

        # GUI zaten VM görüntüsünü gösterecek; dış vnc açmak istemiyorsan config’te kapat.
        if getattr(cfg, "OPEN_VNC_VIEWER", False):
            self.sandbox.launch_vnc_viewer()

        self.llm = load_llm()

        self.stop_event: Optional[threading.Event] = None
        self.worker_thread: Optional[threading.Thread] = None

        self.signals = AgentSignals()
        self.signals.log.connect(self._append_log)
        self.signals.busy.connect(self._set_busy)
        self.signals.finished.connect(self._on_finished)

        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(10)

        # --- VM panel ---
        self.vm_frame = QFrame()
        self.vm_frame.setObjectName("vmFrame")
        vm_layout = QVBoxLayout(self.vm_frame)
        vm_layout.setContentsMargins(0, 0, 0, 0)

        self.vm_view = VMView(self.sandbox)
        self.vm_view.setText("VM ekranı yükleniyor...")
        self.vm_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        vm_layout.addWidget(self.vm_view)
        main_layout.addWidget(self.vm_frame, stretch=10)

        # --- Alt komut paneli ---
        self.bottom = QFrame()
        self.bottom.setObjectName("bottomPanel")
        bottom_layout = QVBoxLayout(self.bottom)
        bottom_layout.setContentsMargins(10, 10, 10, 10)
        bottom_layout.setSpacing(8)

        row = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("Komut gir... (örn: Open web browser)")
        self.run_btn = QPushButton("Çalıştır")
        self.stop_btn = QPushButton("Durdur")
        self.stop_btn.setEnabled(False)

        row.addWidget(self.cmd_input, stretch=1)
        row.addWidget(self.run_btn)
        row.addWidget(self.stop_btn)
        bottom_layout.addLayout(row)

        grid = QGridLayout()
        presets = [
            ("Home", "Click Home file"),
            ("Terminal Aç", "Open terminal"),
            ("Browser Aç", "Open web browser"),
            ("Wikipedia LLM", 'Click on web browser, then open Wikipedia, search "LLM" and press Enter'),
            ("Yaz: merhaba dünya", 'text type "merhaba dünya"'),
            ("Kapat", "bilgisayar kapat"),
        ]
        self.preset_buttons: List[QPushButton] = []
        for i, (title, cmd) in enumerate(presets):
            b = QPushButton(title)
            b.clicked.connect(lambda _, c=cmd: self._preset(c))
            self.preset_buttons.append(b)
            grid.addWidget(b, i // 3, i % 3)
        bottom_layout.addLayout(grid)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(170)
        self.log_box.setObjectName("logBox")
        bottom_layout.addWidget(self.log_box)

        main_layout.addWidget(self.bottom, stretch=0)

        self.run_btn.clicked.connect(self._on_run)
        self.stop_btn.clicked.connect(self._on_stop)
        self.cmd_input.returnPressed.connect(self._on_run)

        # VM ekranını sürekli güncelle
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_vm_screenshot)
        self.timer.start(350)  # full-res olduğu için biraz daha stabil

        self._refresh_vm_screenshot()
        self._append_log("[GUI] Hazır. Komut girip Çalıştır’a basabilirsin.")

    def _style_sheet(self) -> str:
        return """
        QMainWindow { background: #121212; }
        #vmFrame { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px; }
        #vmView { color: #d8d8d8; background: #0f0f0f; border-radius: 10px; }
        #bottomPanel { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px; }
        QLineEdit {
            background: #0f0f0f; color: #eaeaea;
            border: 1px solid #2a2a2a; border-radius: 10px;
            padding: 10px;
        }
        QTextEdit {
            background: #0f0f0f; color: #eaeaea;
            border: 1px solid #2a2a2a; border-radius: 10px;
            padding: 10px;
        }
        QPushButton {
            background: #242424; color: #eaeaea;
            border: 1px solid #2f2f2f; border-radius: 10px;
            padding: 10px 12px;
        }
        QPushButton:hover { background: #2d2d2d; }
        QPushButton:pressed { background: #1f1f1f; }
        QPushButton:disabled { background: #1a1a1a; color: #777; border: 1px solid #222; }
        """

    def _append_log(self, msg: str):
        self.log_box.append(msg)

    def _set_busy(self, busy: bool):
        self.run_btn.setEnabled(not busy)
        self.stop_btn.setEnabled(busy)
        self.cmd_input.setEnabled(not busy)
        for b in self.preset_buttons:
            b.setEnabled(not busy)

        # komut çalışırken screenshot refresh’i biraz yavaşlat (API’yı boğmasın)
        self.timer.setInterval(650 if busy else 350)
        try:
            self.vm_view.input_enabled = (not busy)
        except Exception:
            pass

    def _on_finished(self, msg: str):
        self._append_log(msg)

    def _preset(self, cmd: str):
        self.cmd_input.setText(cmd)

    def _on_stop(self):
        if self.stop_event:
            self.stop_event.set()
            self._append_log("[GUI] Stop sinyali gönderildi.")

    def _on_run(self):
        objective = self.cmd_input.text().strip()
        translated = model.generate(**tokenizer(objective, return_tensors="pt", padding=True))
        for t in translated:
            print( tokenizer.decode(t, skip_special_tokens=True) )

        objective=tokenizer.decode(t, skip_special_tokens=True)
        print(f"kullancı sorusu tam bu: {objective}")
        if not objective:
            self._append_log("[GUI] Komut boş olamaz.")
            return

        low = objective.lower().strip()
        if low in ("bilgisayar kapat", "exit", "quit", "çık", "çıkış"):
            self._append_log("[GUI] Kapatılıyor...")
            QApplication.quit()
            return

        if self.worker_thread and self.worker_thread.is_alive():
            self._append_log("[GUI] Zaten bir komut çalışıyor.")
            return

        self.stop_event = threading.Event()
        self.signals.busy.emit(True)
        self._append_log(f"[GUI] Komut başladı: {objective}")

        def worker():
            try:
                res = run_single_command(
                    self.sandbox,
                    self.llm,
                    objective,
                    log=lambda s: self.signals.log.emit(s),
                    stop_event=self.stop_event,
                )
                self.signals.finished.emit(f"[GUI] Komut sonucu: {res}")
            except Exception:
                self.signals.log.emit("[GUI] HATA:\n" + traceback.format_exc())
            finally:
                self.signals.busy.emit(False)

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _refresh_vm_screenshot(self):
        try:
            img = capture_screen_raw(self.sandbox)
            pm = pil_to_qpixmap(img)
            self.vm_view.set_frame(pm)
        except Exception:
            # log spam olmasın diye sus
            pass



    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

def main():
    app = QApplication(sys.argv)
    w = AgentWindow()
    w.showMaximized()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
