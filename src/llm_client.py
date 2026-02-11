# llm_client.py
from __future__ import annotations

import json
from typing import Any, Dict, List

from huggingface_hub import hf_hub_download
from llama_cpp import Llama
from llama_cpp.llama_chat_format import Qwen3VLChatHandler

from src.config import cfg, JSON_RE
from src.vision import image_to_data_uri


def load_llm() -> Llama:
    model_path = hf_hub_download(repo_id=cfg.GGUF_REPO_ID, filename=cfg.GGUF_MODEL_FILENAME)
    mmproj_path = hf_hub_download(repo_id=cfg.GGUF_REPO_ID, filename=cfg.GGUF_MMPROJ_FILENAME)

    return Llama(
        model_path=model_path,
        chat_handler=Qwen3VLChatHandler(
            clip_model_path=mmproj_path,
            force_reasoning=cfg.FORCE_REASONING,
            image_min_tokens=cfg.IMAGE_MIN_TOKENS,
        ),
        n_ctx=cfg.N_CTX,
        n_batch=cfg.N_BATCH,
        n_gpu_layers=cfg.N_GPU_LAYERS,
        n_threads=cfg.N_THREADS,
        verbose=False,
    )



def _parse_json_obj(text: str) -> Dict[str, Any]:
    m = JSON_RE.search(text.strip())
    if not m:
        raise ValueError(f"Model output is not JSON: {text}")
    return json.loads(m.group(0))


def ask_next_action(llm: Llama, objective: str, screenshot_path: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Returns one action JSON. When done: {"action":"BITTI", ...}
    """
    uri = image_to_data_uri(screenshot_path)

    system = (
        "You are a reactive GUI agent.\n"
        "Given OBJECTIVE, HISTORY (executed actions), and a SCREENSHOT, decide the NEXT single action.\n\n"
        "Return EXACTLY one JSON object. No extra text.\n"
        "Schema:\n"
        "{\n"
        '  "action": "CLICK|DOUBLE_CLICK|RIGHT_CLICK|TYPE|PRESS|HOTKEY|SCROLL|WAIT|NOOP|BITTI",\n'
        '  "x": 0.5,\n'
        '  "y": 0.5,\n'
        '  "text": "",\n'
        '  "key": "",\n'
        '  "keys": [""],\n'
        '  "scroll": 0,\n'
        '  "seconds": 0.0,\n'
        '  "target": "short description",\n'
        '  "confidence": 0.0,\n'
        '  "why_short": "<=12 words"\n'
        "}\n\n"
        "Rules:\n"
        "- Output ONLY valid JSON.\n"
        "- For CLICK/DOUBLE_CLICK/RIGHT_CLICK: set x,y.\n"
        "- For TYPE: set text.\n"
        "- For PRESS: set key.\n"
        "- For HOTKEY: set keys list.\n"
        "- For SCROLL: set scroll (positive=up, negative=down).\n"
        "- For WAIT: set seconds.\n"
        "- If objective is complete, action MUST be BITTI.\n"
        "- Do NOT propose repeating the last executed action unless it clearly failed.\n"
        f"- Safety: Never output x or y within {cfg.MIN_MARGIN} of edges.\n"
    )

    user = (
        f"OBJECTIVE: {objective}\n"
        f"HISTORY: {json.dumps(history, ensure_ascii=False)}\n"
        "Decide the NEXT action from the CURRENT screenshot."
    )

    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": uri}},
                {"type": "text", "text": user},
            ]},
        ],
        temperature=0.1,
        top_p=0.9,
        max_tokens=220,
        stop=["\n\n", "<|im_end|>"],
    )
    return _parse_json_obj(resp["choices"][0]["message"]["content"])
