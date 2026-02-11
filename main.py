# main.py
from __future__ import annotations

import time
from typing import Any, Dict, List

from src.config import cfg
from src.sandbox import Sandbox
from src.llm_client import load_llm, ask_next_action
from src.vision import capture_screen, draw_preview
from src.guards import validate_xy, should_stop_on_repeat
from src.actions import execute_action


# main.py veya llm_client.py
def trim_history(history, keep_last=6):
    if len(history) <= keep_last:
        return history
    return history[-keep_last:]


def main() -> None:
    sandbox = Sandbox(cfg)
    sandbox.start()

    # VNC viewer penceresi açılır (opsiyonel/noVNC)
    if getattr(cfg, "OPEN_VNC_VIEWER", True):
        sandbox.launch_vnc_viewer()

    llm = load_llm()
    print("[DEBUG] cfg.N_CTX =", cfg.N_CTX)

    print("Agent hazır. Çıkmak için 'exit', 'quit' veya 'çık' yaz.")

    # Sonsuz döngü: kullanıcı çıkana kadar devam eder
    while True:
        objective = input("\nKomut gir (veya çık): ").strip()

        # Kullanıcı çıkışı tanıma
        if not objective:
            print("Komut boş olamaz. Tekrar gir.")
            continue
        low = objective.lower()
        if low in ("exit", "quit", "q", "çık", "çıkış"):
            print("Agent kapatılıyor.")
            break

        history: List[Dict[str, Any]] = []

        step = 1
        while True:
            print(f"\n==================== STEP {step} ====================")

            time.sleep(cfg.WAIT_BEFORE_SCREENSHOT_SEC)

            # Anlık ekran görüntüsü al
            img = capture_screen(sandbox, cfg.SCREENSHOT_PATH)

            out: Dict[str, Any] | None = None

            # Model’den bir sonraki eylemi iste
            for attempt in range(cfg.MODEL_RETRY + 1):
                out = ask_next_action(llm, objective, cfg.SCREENSHOT_PATH, trim_history(history))
                action = (out.get("action") or "NOOP").upper()

                # Bitti ifadesi
                if action == "BITTI":
                    print("[MODEL] BITTI -> bu komut için döngü sonlandırıldı.")
                    break

                # CLICK gibi normal koordinatlı eylemler
                if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                    x = float(out.get("x", 0.5))
                    y = float(out.get("y", 0.5))
                    ok, reason = validate_xy(x, y)
                    if ok:
                        break
                    print(f"[WARN] Uygun olmayan koordinat ({reason}), yeniden deneniyor.")
                    history.append({"action": "INVALID_COORDS", "raw": out})
                    out = None
                    continue

                # Diğer eylem türleri doğrudan kabul edilir
                break

            # Eğer out None ise model geçerli bir eylem üretemedi
            if out is None:
                print("[ERROR] Model geçerli bir aksiyon üretemedi, bu komut için döngü sonlandırılıyor.")
                break

            print("[MODEL]", out)

            # Repeat guard: aynı eylem tekrarı ise dur
            stop, why = should_stop_on_repeat(history, out)
            if stop:
                print(f"[STOP] {why} -> bu komut için döngü sonlandırıldı.")
                break

            # Eğer model BITTI verdiyse
            if (out.get("action") or "").upper() == "BITTI":
                print("Model bu komut için tamamlandı dedi. Yeni komut isteği geliyor.")
                break

            # Preview çizimi (opsiyonel)
            action = (out.get("action") or "").upper()
            if action in ("CLICK", "DOUBLE_CLICK", "RIGHT_CLICK"):
                preview_path = cfg.PREVIEW_PATH_TEMPLATE.format(i=step)
                draw_preview(img, float(out["x"]), float(out["y"]), preview_path)

            # Aksiyonunu uygula
            execute_action(sandbox, out)
            history.append(out)

            step += 1

            # Adım sayısı çok uzarsa güvenlik
            if step > cfg.MAX_STEPS:
                print("[STOP] MAX_STEPS aşıldı, bu komut için döngü sonlandırıldı.")
                break

        # Burada tek bir objective için döngü bitsin,
        # sonra tekrar kullanıcıdan yeni komut iste
        print("Bir sonraki komut için hazır.")


if __name__ == "__main__":
    main()
