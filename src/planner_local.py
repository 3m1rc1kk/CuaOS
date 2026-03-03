# planner_local.py — Local GGUF planner using llama-cpp-python (text-only)
from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Dict, List

from src.config import cfg, JSON_RE
from src.planner import (
    Plan,
    PlanStep,
    Planner,
    PLANNER_SYSTEM_PROMPT,
    build_planner_user_prompt,
    validate_plan_json,
)


def auto_gpu_layers(model_path: str) -> int:
    """
    Automatically determine the optimal number of GPU layers for the PLANNER model.

    IMPORTANT: The planner typically runs alongside the executor model (Qwen3-VL)
    which is already loaded on GPU. Running two llama.cpp models on the same GPU
    causes 'double free' crashes due to CUDA context conflicts.

    Strategy:
    1. Check if another llama.cpp model is likely already using GPU
       (cfg.N_GPU_LAYERS != 0 means executor is on GPU)
    2. If so → CPU-only (0 layers) to avoid crashes
    3. If not → detect VRAM and calculate optimal layers
    """
    from src.config import cfg as _cfg

    # If the executor (Qwen3-VL) is already on GPU, planner MUST use CPU
    # to avoid double-free crashes from two llama.cpp instances sharing CUDA
    if _cfg.N_GPU_LAYERS != 0:
        print("[PLANNER] Executor model is on GPU — planner will use CPU-only "
              "to avoid CUDA conflicts.")
        return 0

    try:
        # Get available VRAM in MB
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            print("[PLANNER] nvidia-smi not available, using CPU only.")
            return 0

        # Parse all GPUs, use the one with most free VRAM
        vram_values = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    vram_values.append(int(line))
                except ValueError:
                    pass

        if not vram_values:
            print("[PLANNER] Could not parse VRAM info, using CPU only.")
            return 0

        free_vram_mb = max(vram_values)
        print(f"[PLANNER] Available VRAM: {free_vram_mb} MB")

        # Get model file size
        try:
            model_size_mb = os.path.getsize(model_path) / (1024 * 1024)
        except OSError:
            print("[PLANNER] Could not read model file size, using CPU only.")
            return 0

        print(f"[PLANNER] Model file size: {model_size_mb:.0f} MB")

        # Reserve 500MB for overhead (KV cache, CUDA context, etc.)
        usable_vram = max(0, free_vram_mb - 500)

        if usable_vram <= 0:
            print("[PLANNER] Not enough VRAM after overhead, using CPU only.")
            return 0

        # Estimate: model_size approximates total weight memory
        # Typical GGUF models have 32-80 layers
        estimated_total_layers = 40
        ratio = usable_vram / model_size_mb

        if ratio >= 1.0:
            print(f"[PLANNER] Model fits in VRAM (ratio={ratio:.2f}), using all GPU layers.")
            return -1
        else:
            layers = int(estimated_total_layers * ratio)
            layers = max(1, layers)
            print(f"[PLANNER] Partial GPU offload: {layers}/{estimated_total_layers} layers "
                  f"(VRAM ratio={ratio:.2f})")
            return layers

    except FileNotFoundError:
        print("[PLANNER] nvidia-smi not found, using CPU only.")
        return 0
    except Exception as e:
        print(f"[PLANNER] Auto GPU detection error: {e}, using CPU only.")
        return 0


class LocalGGUFPlanner(Planner):
    """Plan generation using a local text-only GGUF model via llama-cpp-python."""

    def __init__(self):
        model_path = self._resolve_model_path()

        # Auto GPU layers if set to -1
        n_gpu_layers = cfg.PLANNER_N_GPU_LAYERS
        if n_gpu_layers == -1:
            print("[PLANNER] Auto-detecting optimal GPU layers...")
            n_gpu_layers = auto_gpu_layers(model_path)

        print(f"[PLANNER] Loading model from: {model_path}")
        print(f"[PLANNER] GPU layers: {n_gpu_layers}, threads: {cfg.PLANNER_N_THREADS}, "
              f"ctx: {cfg.PLANNER_N_CTX}")

        from llama_cpp import Llama
        self._llm = Llama(
            model_path=model_path,
            n_ctx=cfg.PLANNER_N_CTX,
            n_threads=cfg.PLANNER_N_THREADS,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )
        print("[PLANNER] Local GGUF planner ready.")

    @staticmethod
    def _resolve_model_path() -> str:
        """
        Resolve model path in priority order:
        1. Direct local file path (PLANNER_GGUF_LOCAL_PATH)
        2. HuggingFace Hub download (PLANNER_GGUF_REPO_ID + PLANNER_GGUF_MODEL_FILENAME)
        """
        local_path = cfg.PLANNER_GGUF_LOCAL_PATH.strip()
        if local_path:
            if not os.path.isfile(local_path):
                raise FileNotFoundError(
                    f"PLANNER_GGUF_LOCAL_PATH does not exist: {local_path}")
            if not local_path.lower().endswith(".gguf"):
                raise ValueError(
                    f"PLANNER_GGUF_LOCAL_PATH is not a .gguf file: {local_path}")
            print(f"[PLANNER] Using local model file: {local_path}")
            return local_path

        repo_id = cfg.PLANNER_GGUF_REPO_ID.strip()
        filename = cfg.PLANNER_GGUF_MODEL_FILENAME.strip()

        if not repo_id or not filename:
            raise ValueError(
                "Either set PLANNER_GGUF_LOCAL_PATH to a local .gguf file, "
                "or set both PLANNER_GGUF_REPO_ID and PLANNER_GGUF_MODEL_FILENAME "
                "for HuggingFace Hub download."
            )

        print(f"[PLANNER] Downloading from HuggingFace: {repo_id}/{filename}")
        from huggingface_hub import hf_hub_download
        return hf_hub_download(repo_id=repo_id, filename=filename)

    def plan(self, objective: str, context: str = "") -> Plan:
        user_prompt = build_planner_user_prompt(objective, context)

        resp = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            top_p=0.9,
            max_tokens=max(cfg.PLANNER_MAX_TOKENS, 2048),
            stop=["\n\n\n", "<|im_end|>"],
        )

        raw_text = resp["choices"][0]["message"]["content"]
        print(f"[PLANNER] Raw output ({len(raw_text)} chars):\n{raw_text[:300]}...")
        return self._parse_plan(raw_text, objective)

    @staticmethod
    def _parse_plan(raw_text: str, objective: str) -> Plan:
        """Parse plan from raw LLM output. Tries JSON first, falls back to text parsing."""
        text = raw_text.strip()

        # 1. Try JSON parsing first
        m = JSON_RE.search(text)
        if m:
            try:
                data: Dict[str, Any] = json.loads(m.group(0))
                data.setdefault("objective", objective)
                validate_plan_json(data)
                print("[PLANNER] Parsed plan from JSON output.")
                return Plan.from_dict(data)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[PLANNER] JSON found but invalid ({e}), trying text fallback...")

        # 2. Fallback: parse numbered text steps
        print("[PLANNER] No valid JSON — parsing plain text steps as fallback...")
        return LocalGGUFPlanner._parse_text_plan(text, objective)

    @staticmethod
    def _parse_text_plan(raw_text: str, objective: str) -> Plan:
        """
        Parse a plain-text numbered plan into a Plan object.
        Handles patterns like:
          1. Open the browser
          2. Navigate to Wikipedia
          - Step one: open browser
          Step 1: Open browser
        """
        steps: List[PlanStep] = []

        # Match lines starting with: "1." "1)" "- " "Step 1:" etc.
        step_pattern = re.compile(
            r'^\s*(?:'
            r'(\d+)\s*[.):\-]\s*'           # "1." "1)" "1:" "1-"
            r'|[-•*]\s+'                      # "- " "• " "* "
            r'|(?:step|adım)\s+(\d+)\s*[.:]\s*'  # "Step 1:" "Adım 1:"
            r')(.+)',
            re.IGNORECASE
        )

        for line in raw_text.split('\n'):
            line = line.strip()
            if not line:
                continue
            m = step_pattern.match(line)
            if m:
                # Extract the step title (last capture group with content)
                title = (m.group(3) or "").strip()
                # Remove trailing periods
                title = title.rstrip('.')
                if not title:
                    continue
                # Truncate very long titles (some models produce paragraphs)
                if len(title) > 120:
                    title = title[:117] + "..."

                step_num = len(steps) + 1
                steps.append(PlanStep(
                    id=f"S{step_num}",
                    title=title,
                    rationale="(auto-parsed from text)",
                    success_criteria=[f"{title} completed successfully"],
                    max_attempts=2,
                ))

        if not steps:
            # Last resort: treat each non-empty line as a step
            for i, line in enumerate(raw_text.split('\n'), 1):
                line = line.strip()
                if line and len(line) > 5 and i <= 15:
                    if len(line) > 120:
                        line = line[:117] + "..."
                    steps.append(PlanStep(
                        id=f"S{i}",
                        title=line,
                        rationale="(auto-parsed from text)",
                        success_criteria=[f"{line} completed"],
                        max_attempts=2,
                    ))

        if not steps:
            raise ValueError(
                f"Could not parse any steps from planner output:\n{raw_text[:500]}")

        print(f"[PLANNER] Parsed {len(steps)} steps from plain text.")
        for s in steps:
            print(f"  {s.id}. {s.title}")

        return Plan(
            objective=objective,
            steps=steps,
            assumptions=["Plan auto-parsed from text output"],
            confidence=0.4,  # Lower confidence for text-parsed plans
        )
