# sandbox.py
import base64
import json
import os
import subprocess
import time
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

import requests
from PIL import Image


def _safe_getattr(obj, key: str, default):
    return getattr(obj, key, default)


def _docker_running(name: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and r.stdout.strip().lower() == "true"


def _docker_exists(name: str) -> bool:
    r = subprocess.run(
        ["docker", "inspect", name],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0



def _docker_env(name: str) -> Dict[str, str]:
    """Return container env as dict via docker inspect."""
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{json .Config.Env}}", name],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return {}
    try:
        env_list = json.loads((r.stdout or "").strip() or "[]")
        out: Dict[str, str] = {}
        for item in env_list:
            if isinstance(item, str) and "=" in item:
                k, v = item.split("=", 1)
                out[k] = v
        return out
    except Exception:
        return {}

def _parse_sse_or_json(text: str) -> Any:
    """
    The /cmd endpoint sometimes returns JSON, sometimes text/event-stream (SSE).
    - JSON: {"success": true, ...}
    - SSE: data: {...}\n\n (may contain multiple events)
    Returns the last JSON object found.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty response body")

    # Plain JSON
    if text.startswith("{") and text.endswith("}"):
        return json.loads(text)

    last_obj = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
            if payload.startswith("{") and payload.endswith("}"):
                try:
                    last_obj = json.loads(payload)
                except Exception:
                    pass

    if last_obj is not None:
        return last_obj

    # Fallback: try to extract any JSON substring
    l = text.find("{")
    r = text.rfind("}")
    if l != -1 and r != -1 and r > l:
        return json.loads(text[l : r + 1])

    raise ValueError(f"Could not parse response (first 200 chars): {text[:200]!r}")


class Sandbox:
    """
    Minimal "computer-server" REST wrapper for the trycua/cua-xfce container.
    Host -> container port map:
      - API (container:8000)  -> host:API_PORT
      - VNC (container:5901)  -> host:VNC_PORT
      - noVNC (container:6901)-> host:NOVNC_PORT

    These access points are documented as "Common Access Points" in the CUA docs.
    """

    def __init__(self, cfg):
        self.cfg = cfg

        self.container_name = _safe_getattr(cfg, "SANDBOX_NAME", "cua_xfce_agent")
        self.image = _safe_getattr(cfg, "SANDBOX_IMAGE", "trycua/cua-xfce:latest")

        self.api_host = _safe_getattr(cfg, "API_HOST", "127.0.0.1")
        self.host_api_port = int(_safe_getattr(cfg, "API_PORT", 8000))  # host port
        self.host_vnc_port = int(_safe_getattr(cfg, "VNC_PORT", 5901))
        self.host_novnc_port = int(_safe_getattr(cfg, "NOVNC_PORT", 6901))

        # container fixed ports
        self.container_api_port = 8000
        self.container_vnc_port = 5901
        self.container_novnc_port = 6901

        self.base_url = f"http://{self.api_host}:{self.host_api_port}"
        self.cmd_url = f"{self.base_url}/cmd"
        self.status_url = f"{self.base_url}/status"

        self.vnc_resolution = _safe_getattr(cfg, "VNC_RESOLUTION", "1280x720")
        self.vnc_col_depth = int(_safe_getattr(cfg, "VNC_COL_DEPTH", 24))
        self.shm_size = _safe_getattr(cfg, "DOCKER_SHM_SIZE", "512m")

        # screen size cache (avoid spamming /cmd)
        self._screen_cache: Optional[Tuple[int, int]] = None
        self._screen_cache_ts: float = 0.0
        self._screen_cache_ttl: float = float(_safe_getattr(cfg, "SCREEN_CACHE_TTL", 0.5))

        self.api_ready_timeout = float(_safe_getattr(cfg, "API_READY_TIMEOUT", 180.0))
        self.api_ready_interval = float(_safe_getattr(cfg, "API_READY_INTERVAL", 1.0))

        self.http_timeout = float(_safe_getattr(cfg, "HTTP_TIMEOUT", 30.0))

    # -----------------------
    # Lifecycle
    # -----------------------
    def start(self) -> None:
        """
        - If the container is already running: just wait for API readiness.
        - If not running: start it with docker run and wait for API readiness.
        """
        if _docker_running(self.container_name):
            env = _docker_env(self.container_name)
            want_res = str(self.vnc_resolution)
            want_depth = str(self.vnc_col_depth)
            if env.get("VNC_RESOLUTION") != want_res or env.get("VNC_COL_DEPTH") != want_depth:
                print("[SANDBOX] VNC env changed -> restarting container...")
                self.stop()
            else:
                print(f"[SANDBOX] Container already running: {self.container_name}")
                self._wait_api_ready(timeout=self.api_ready_timeout)
                return

        # Remove stopped container with the same name if it exists (port mapping may have changed)
        if _docker_exists(self.container_name) and not _docker_running(self.container_name):
            subprocess.run(["docker", "rm", "-f", self.container_name], check=False)

        print("[SANDBOX] Starting container...")
        cmd = [
            "docker", "run", "-d",
            "--name", self.container_name,
            f"--shm-size={self.shm_size}",
            "-e", f"VNC_RESOLUTION={self.vnc_resolution}",
            "-e", f"VNC_COL_DEPTH={self.vnc_col_depth}",
            "-p", f"{self.host_vnc_port}:{self.container_vnc_port}",
            "-p", f"{self.host_novnc_port}:{self.container_novnc_port}",
            "-p", f"{self.host_api_port}:{self.container_api_port}",
            self.image,
        ]
        subprocess.run(cmd, check=True)
        self._wait_api_ready(timeout=self.api_ready_timeout)

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.container_name], check=False)

    def launch_vnc_viewer(self) -> None:
        """
        Opens TigerVNC viewer if available; otherwise prints noVNC URL.
        """
        try:
            subprocess.Popen(["vncviewer", f"127.0.0.1:{self.host_vnc_port}"])
            print("[SANDBOX] VNC viewer launched.")
        except FileNotFoundError:
            print("[SANDBOX] vncviewer not found. Use noVNC:",
                  f"http://127.0.0.1:{self.host_novnc_port}")

    # -----------------------
    # Readiness
    # -----------------------
    def _wait_api_ready(self, timeout: float) -> None:
        """
        Some image versions have /status, some don't.
        Strategy:
          1) Try GET /status (if available)
          2) Otherwise try POST /cmd get_screen_size
        """
        print(f"[SANDBOX] Waiting up to {int(timeout)}s for API to become ready at {self.cmd_url} ...")
        t0 = time.time()
        last_err: Optional[Exception] = None

        while time.time() - t0 < timeout:
            # 1) /status
            try:
                r = requests.get(self.status_url, timeout=self.http_timeout)
                if r.status_code == 200:
                    # some versions may return empty body; 200 is sufficient
                    print("[SANDBOX] API ready (/status).")
                    return
            except Exception as e:
                last_err = e

            # 2) /cmd get_screen_size
            try:
                res = self._post_cmd("get_screen_size", {})
                if isinstance(res, dict) and res.get("success") is True:
                    print("[SANDBOX] API ready (/cmd).")
                    return
            except Exception as e:
                last_err = e

            time.sleep(self.api_ready_interval)

        raise TimeoutError(f"Sandbox API did not become ready in time. Last error: {last_err}")

    # -----------------------
    # Low-level /cmd
    # -----------------------
    def _post_cmd(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        body = {"command": command, "params": params or {}}
        r = requests.post(self.cmd_url, json=body, timeout=self.http_timeout)
        parsed = _parse_sse_or_json(r.text)
        if not isinstance(parsed, dict):
            raise ValueError(f"Unexpected parsed type from /cmd: {type(parsed)}")
        return parsed

    # -----------------------
    # Public actions
    # -----------------------
    def screenshot(self) -> Image.Image:
        """
        Expected format: {"success": true, "image_data": "<base64_png>"}
        """
        res = self._post_cmd("screenshot", {})
        if not (isinstance(res, dict) and res.get("success") is True and "image_data" in res):
            raise ValueError(f"Unexpected screenshot content: {res}")

        raw = base64.b64decode(res["image_data"])
        img = Image.open(BytesIO(raw)).convert("RGB")
        return img

    def get_screen_size(self) -> Tuple[int, int]:
        """
        Accepted formats:
        A) {"success": true, "size": {"width": 1395, "height": 1016}}
        B) {"success": true, "width": 1395, "height": 1016}
        """
        now = time.time()
        if self._screen_cache and (now - self._screen_cache_ts) < self._screen_cache_ttl:
            return self._screen_cache

        res = self._post_cmd("get_screen_size", {})
        if not (isinstance(res, dict) and res.get("success") is True):
            raise ValueError(f"Invalid screen size from server: {res}")

        size = res.get("size")
        if isinstance(size, dict) and "width" in size and "height" in size:
            w, h = int(size["width"]), int(size["height"])
            self._screen_cache = (w, h)
            self._screen_cache_ts = now
            return w, h

        if "width" in res and "height" in res:
            w, h = int(res["width"]), int(res["height"])
            self._screen_cache = (w, h)
            self._screen_cache_ts = now
            return w, h

        raise ValueError(f"Invalid screen size shape: {res}")

    def _norm_to_px(self, x: float, y: float) -> Tuple[int, int]:
        w, h = self.get_screen_size()
        # x/y normalized (0..1). Clamp and map into [0..w-1]/[0..h-1]
        xn = max(0.0, min(1.0, float(x)))
        yn = max(0.0, min(1.0, float(y)))
        px = int(xn * max(0, w - 1))
        py = int(yn * max(0, h - 1))
        return px, py

    def left_click_norm(self, x: float, y: float) -> None:
        px, py = self._norm_to_px(x, y)
        self._post_cmd("left_click", {"x": px, "y": py})

    def right_click_norm(self, x: float, y: float) -> None:
        px, py = self._norm_to_px(x, y)
        self._post_cmd("right_click", {"x": px, "y": py})

    def double_click_norm(self, x: float, y: float) -> None:
        px, py = self._norm_to_px(x, y)
        self._post_cmd("double_click", {"x": px, "y": py})

    def type_text(self, text: str) -> None:
        self._post_cmd("type_text", {"text": str(text)})

    def press_key(self, key: str) -> None:
        self._post_cmd("press_key", {"key": str(key)})

    def hotkey(self, keys) -> None:
        self._post_cmd("hotkey", {"keys": list(keys)})

    def scroll(self, amount: int) -> None:
        self._post_cmd("scroll", {"amount": int(amount)})

    # --- Manual control helpers (GUI) ---
    def mouse_move_norm(self, x: float, y: float) -> None:
        px, py = self._norm_to_px(x, y)
        self._post_cmd("move_cursor", {"x": px, "y": py})

    def mouse_down(self, button: int = 1) -> None:
        self._post_cmd("mouse_down", {"button": int(button)})

    def mouse_up(self, button: int = 1) -> None:
        self._post_cmd("mouse_up", {"button": int(button)})

    def drag_to_norm(self, x: float, y: float, button: int = 1) -> None:
        px, py = self._norm_to_px(x, y)
        self._post_cmd("drag_to", {"x": px, "y": py, "button": int(button)})

    def key_down(self, key: str) -> None:
        self._post_cmd("key_down", {"key": str(key)})

    def key_up(self, key: str) -> None:
        self._post_cmd("key_up", {"key": str(key)})

    def wait(self, seconds: float) -> None:
        time.sleep(float(seconds))
