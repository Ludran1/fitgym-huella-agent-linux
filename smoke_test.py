#!/usr/bin/env python3
"""
Smoke test del lector ZKTeco SLK20R via libzkfp.so NATIVO (ctypes, sin Mono/pythonnet).
Flujo: Init -> GetDeviceCount -> OpenDevice -> enrolar (3 capturas) -> DBMerge -> DBAdd
       -> identificar una huella nueva -> DBIdentify -> imprimir fid + score.

Correr con el venv del kit:
    huella-agent-linux/.venv/bin/python huella-agent-linux/smoke_test.py
"""
import os
import sys
import time

# Cargar las libs del SDK Linux (libzkfp.so + deps) SOLO para este proceso: su carpeta va
# en LD_LIBRARY_PATH y nos re-ejecutamos una vez. Override con `ZKFP_LIB_DIR=/ruta/lib-x64`.
_SDK_LIB = os.environ.get("ZKFP_LIB_DIR") or os.path.expanduser(
    "~/Downloads/zkfinger-linux-sdk/SDK/lib-x64")
if os.path.isdir(_SDK_LIB) and _SDK_LIB not in os.environ.get("LD_LIBRARY_PATH", "").split(":"):
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = _SDK_LIB + (":" + cur if cur else "")
    os.execv(sys.executable, [sys.executable] + sys.argv)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zkfp_native import ZKFP, ZKFPError  # noqa: E402

CAPTURE_TIMEOUT_S = 20
POLL_S = 0.2


def wait_for_finger(zk, prompt):
    """Pide un dedo y poolea acquire() hasta capturar (bytes) o timeout (None)."""
    print(f"\n>>> {prompt}")
    deadline = time.time() + CAPTURE_TIMEOUT_S
    while time.time() < deadline:
        tmpl = zk.acquire()
        if tmpl:
            print(f"    capturado ({len(tmpl)} bytes).")
            return tmpl
        time.sleep(POLL_S)
    print("    [TIMEOUT] no se detectó dedo.")
    return None


def main():
    zk = ZKFP()
    zk.init()
    try:
        n = zk.device_count()
        print(f"Dispositivos detectados: {n}")
        if n < 1:
            print("[FALLO] 0 lectores. Revisá lsusb + udev (detect_reader.sh).")
            return 1

        w, h = zk.open()
        print(f"Device 0 abierto. Imagen {w}x{h}. Modelo SLK20R esperado.")

        # --- Enrolar: 3 capturas del MISMO dedo, merge en un template ---
        templates = []
        for i in range(3):
            tmpl = wait_for_finger(zk, f"Enrolar — apoyá el MISMO dedo ({i + 1}/3). Levantá entre capturas.")
            if not tmpl:
                print("[FALLO] enrolamiento incompleto.")
                return 1
            templates.append(tmpl)
            time.sleep(0.8)

        reg = zk.merge(*templates)
        zk.db_add(1, reg)
        print(f"\nEnrolado OK como fid=1 (template {len(reg)} bytes).")

        # --- Identificar: capturar de nuevo y matchear contra la DB en memoria ---
        probe = wait_for_finger(zk, "Identificar — apoyá el MISMO dedo otra vez.")
        if not probe:
            print("[FALLO] no capturé huella para identificar.")
            return 1
        result = zk.identify(probe)
        if result:
            fid, score = result
            print(f"\n[OK] MATCH fid={fid} score={score}  ✅ Cadena completa funciona.")
            return 0
        print("\n[?] Sin match. El lector capturó pero no identificó.")
        return 2
    except ZKFPError as e:
        print(f"[FALLO] {e}")
        return 1
    finally:
        zk.close()
        print("\nTerminate() llamado. Fin.")


if __name__ == "__main__":
    sys.exit(main())
