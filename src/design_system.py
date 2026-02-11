"""
CUA Mission Control — Design System
Referans: arayuz.py.py (EyeControl OS mavi teması)
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Colors:
    BG_DEEPEST: str = "#060e1a"
    BG_BASE: str = "#0a1929"
    BG_PANEL: str = "#0f2744"
    BG_CARD: str = "#1e3a5f"
    BG_INPUT: str = "#0d1f36"
    BG_ACCENT: str = "#0d47a1"
    PRIMARY: str = "#2196f3"
    PRIMARY_LIGHT: str = "#64b5f6"
    PRIMARY_DARK: str = "#1565c0"
    TEXT: str = "#e3f2fd"
    TEXT_DIM: str = "#90caf9"
    TEXT_MUTED: str = "#5c7ea3"
    GREEN: str = "#00e676"
    GREEN_BG: str = "#4caf50"
    ORANGE: str = "#ff9800"
    RED: str = "#f44336"
    BORDER: str = "#1a3a5c"
    BORDER_BRIGHT: str = "#2196f3"

C = Colors()

@dataclass(frozen=True)
class Sizing:
    RADIUS_SM: int = 6
    RADIUS_MD: int = 10
    RADIUS_LG: int = 14
    PAD_XS: int = 4
    PAD_SM: int = 8
    PAD_MD: int = 12
    PAD_LG: int = 16

S = Sizing()

FONT_FAMILY = '"Segoe UI", "Roboto", "Ubuntu", sans-serif'

def build_stylesheet() -> str:
    return f"""
    * {{ font-family: {FONT_FAMILY}; }}
    QMainWindow {{ background: {C.BG_DEEPEST}; }}

    /* --- Panels --- */
    QFrame#topBar {{
        background: {C.BG_PANEL};
        border-bottom: 1px solid {C.BORDER};
        padding: 6px 12px;
    }}
    QFrame#leftPanel {{
        background: {C.BG_PANEL};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_LG}px;
    }}
    QFrame#centerPanel {{
        background: {C.BG_BASE};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_LG}px;
    }}
    QFrame#rightPanel {{
        background: {C.BG_PANEL};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_LG}px;
    }}
    QFrame#bottomPanel {{
        background: {C.BG_PANEL};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_LG}px;
    }}

    /* --- VMView --- */
    QLabel#vmView {{
        background: #000;
        border-radius: {S.RADIUS_MD}px;
        color: {C.TEXT_DIM};
    }}

    /* --- Text inputs --- */
    QLineEdit {{
        background: {C.BG_INPUT};
        color: {C.TEXT};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_MD}px;
        padding: 10px 14px;
        font-size: 13px;
    }}
    QLineEdit:focus {{
        border-color: {C.PRIMARY};
    }}

    /* --- Text areas --- */
    QTextEdit {{
        background: {C.BG_INPUT};
        color: {C.TEXT};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_MD}px;
        padding: 8px;
        font-size: 12px;
    }}
    QTextEdit#logBox {{
        color: {C.GREEN};
        font-family: "Consolas", "Ubuntu Mono", monospace;
        font-size: 11px;
    }}

    /* --- Buttons --- */
    QPushButton {{
        background: {C.BG_CARD};
        color: {C.TEXT};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_SM}px;
        padding: 8px 16px;
        font-weight: bold;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background: {C.PRIMARY_DARK};
        border-color: {C.PRIMARY};
    }}
    QPushButton:pressed {{
        background: {C.BG_ACCENT};
    }}
    QPushButton:disabled {{
        background: {C.BG_BASE};
        color: {C.TEXT_MUTED};
        border-color: {C.BG_PANEL};
    }}
    QPushButton#runBtn {{
        background: {C.PRIMARY_DARK};
        border-color: {C.PRIMARY};
    }}
    QPushButton#runBtn:hover {{
        background: {C.PRIMARY};
        color: {C.BG_BASE};
    }}
    QPushButton#stopBtn {{
        background: #7f1d1d;
        border-color: {C.RED};
    }}
    QPushButton#stopBtn:hover {{
        background: {C.RED};
        color: white;
    }}
    QPushButton#presetBtn {{
        background: {C.BG_CARD};
        border: 1px solid {C.BORDER};
        padding: 6px 12px;
        font-size: 11px;
    }}
    QPushButton#presetBtn:hover {{
        background: {C.PRIMARY_DARK};
        border-color: {C.PRIMARY_LIGHT};
    }}

    /* --- Labels --- */
    QLabel {{
        color: {C.TEXT};
    }}
    QLabel#sectionTitle {{
        font-size: 13px;
        font-weight: bold;
        color: {C.PRIMARY_LIGHT};
        padding: 4px 0;
    }}
    QLabel#statusDot {{
        font-size: 11px;
    }}
    QLabel#metricValue {{
        font-size: 18px;
        font-weight: bold;
        color: {C.TEXT};
    }}
    QLabel#metricLabel {{
        font-size: 10px;
        color: {C.TEXT_MUTED};
    }}

    /* --- List widget --- */
    QListWidget {{
        background: {C.BG_INPUT};
        color: {C.TEXT};
        border: 1px solid {C.BORDER};
        border-radius: {S.RADIUS_SM}px;
        font-size: 11px;
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 4px 8px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background: {C.PRIMARY_DARK};
    }}

    /* --- Scroll bars --- */
    QScrollBar:vertical {{
        background: {C.BG_BASE};
        width: 8px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {C.BORDER};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {C.PRIMARY_DARK};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    """
