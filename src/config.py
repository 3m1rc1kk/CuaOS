import re
from dataclasses import dataclass
from typing import Tuple

@dataclass
class CFG:
    # ----------------------
    # LLM Model config
    # ----------------------
    GGUF_REPO_ID: str = "mradermacher/Qwen3-VL-8B-Instruct-abliterated-v2.0-GGUF"
    GGUF_MODEL_FILENAME: str = "Qwen3-VL-8B-Instruct-abliterated-v2.0.Q5_K_S.gguf"
    GGUF_MMPROJ_FILENAME: str = "Qwen3-VL-8B-Instruct-abliterated-v2.0.mmproj-f16.gguf"
    # Llama runtime
    N_CTX: int = 2048
    N_THREADS: int = 12
    N_GPU_LAYERS: int = -1
    N_BATCH: int = 32

    FORCE_REASONING: bool = False

    # Repeat guard
    STOP_ON_REPEAT: bool = True

    # Aynı noktaya tıklamayı yakalamak için tolerans
    REPEAT_XY_EPS: float = 0.01     # normalized 0..1

    # VM ekranını pencere olarak aç
    OPEN_VNC_VIEWER: bool = True
    IMAGE_MIN_TOKENS: int = 1024

    # ----------------------
    # Sandbox Docker config
    # ----------------------
    SANDBOX_IMAGE: str = "docker.io/trycua/cua-xfce:latest"
    SANDBOX_NAME: str = "cua_xfce_agent"

    # (Host side) VNC & API ports. 
    # container 5901: VNC
    # container 6901: noVNC (mapped externally)
    # container 8000: Computer Server API
    VNC_PORT: int = 5901
    NOVNC_PORT: int = 6901
    API_PORT: int = 8001

    # Docker run settings
    DOCKER_SHM_SIZE: str = "512m"
    VNC_RESOLUTION: str = "1920x1080"
    VNC_COL_DEPTH: int = 24

    # If True: launch VNC viewer automatically
    OPEN_VNC_VIEWER: bool = True

    # ----------------------
    # Agent loop timing
    # ----------------------
    WAIT_BEFORE_SCREENSHOT_SEC: float = 2.2
    PAUSE_AFTER_CLICK_SEC: float = 0.25

    SCREENSHOT_PATH: str = "./img/screen.png"
    MAX_DIM: int = 640

    PREVIEW_PATH_TEMPLATE: str = "./img/click_preview_step_{i}.png"

    MIN_MARGIN: float = 0.02
    CONFIDENCE_MIN: float = 0.15

    WAIT_CHANGE_TIMEOUT: float = 3.0
    WAIT_CHANGE_INTERVAL: float = 0.25
    CHANGE_THRESHOLD: float = 0.02

    MAX_STEPS: int = 20
    MODEL_RETRY: int = 2
    API_READY_TIMEOUT: int = 120  # saniye

    # Sandbox screen size cache (seconds)
    SCREEN_CACHE_TTL: float = 0.5

    # Anti-loop
    REPEAT_CLICK_DISTANCE_PX: int = 10

    ALLOWED_PRESS_KEYS: Tuple[str, ...] = (
        "enter", "tab", "esc", "backspace", "delete",
        "up", "down", "left", "right",
        "home", "end", "pageup", "pagedown",
        "space"
    )

    ALLOWED_HOTKEYS: Tuple[Tuple[str, ...], ...] = (
        ("ctrl", "l"),
        ("ctrl", "t"),
        ("ctrl", "w"),
        ("alt", "tab"),
    )


# Instantiate config
cfg = CFG()

# ----------------------
# Regex / MIME tables
# ----------------------

# vision.image_to_data_uri needs this
IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# Used in llm_client to parse JSON from model text
JSON_RE = re.compile(r"\{.*\}", re.S)
