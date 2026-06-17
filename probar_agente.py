#!/usr/bin/env python3
"""
Prueba e2e del AGENTE corriendo (localhost:8000) con el lector real, vía el contrato HTTP
que usa el frontend. Valida capture+enroll+identify de punta a punta (no solo el SDK).

Requiere: `agent.py` corriendo en OTRA terminal.
Uso:      .venv/bin/python probar_agente.py
Flujo:    /health -> capture x3 (apoyás dedo) -> enroll -> identify (apoyás dedo) -> MATCH

No usa dependencias extra (urllib stdlib). cliente_id/tenant_id son de demo.
"""
import json
import sys
import urllib.request

URL = "http://127.0.0.1:8000"
CLIENTE = "DEMO-CLIENTE-1"
TENANT = "DEMO-TENANT"


def call(path, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        URL + path, data=data, method="POST" if data else "GET",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or "{}")
    except Exception as e:  # noqa: BLE001
        print(f"[FALLO] no pude hablar con el agente en {URL} ({e}).")
        print("        ¿Está corriendo `agent.py` en otra terminal?")
        sys.exit(1)


def main():
    st, health = call("/health")
    print(f"/health → {health}")
    if health.get("reader") != "connected":
        print("[FALLO] el agente no ve el lector (reader != connected).")
        return 1

    # --- enrolar: 3 capturas del mismo dedo ---
    templates = []
    for i in range(3):
        input(f"\n[Captura {i+1}/3] Apoyá el MISMO dedo y dale ENTER (levantá entre capturas)...")
        st, data = call("/api/fingerprint/capture", {"timeout": 15})
        if st != 200:
            print(f"[FALLO] capture {i+1} → {st} {data}")
            return 1
        templates.append(data["template"])
        print(f"  capturado ({len(data['template'])} chars base64).")

    st, data = call("/api/fingerprint/enroll", {
        "cliente_id": CLIENTE, "tenant_id": TENANT,
        "template1": templates[0], "template2": templates[1], "template3": templates[2],
    })
    if st != 200 or not data.get("ok"):
        print(f"[FALLO] enroll → {st} {data}")
        return 1
    print(f"\nEnrolado OK como uid={data.get('uid')} (cliente {CLIENTE}).")

    # --- identificar ---
    input("\n[Identificar] Apoyá el MISMO dedo y dale ENTER...")
    st, data = call("/api/fingerprint/identify", {"tenant_id": TENANT})
    if st == 200 and data.get("cliente_id") == CLIENTE:
        print(f"\n[OK] MATCH cliente_id={data['cliente_id']} score={data.get('score')}  ✅ Agente e2e OK.")
        return 0
    if st == 404:
        print("\n[?] 404 sin match. Capturó pero no identificó (¿otro dedo?).")
        return 2
    print(f"\n[FALLO] identify → {st} {data}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
