#!/usr/bin/env python3
"""
Agente de huella LINUX para DEMOS portátiles (laptop Linux + SLK20R via libzkfp.so nativo).

Sirve el MISMO contrato HTTP que ya consume el frontend (src/lib/huellaApi.ts):
    GET  /health                       -> {ok, reader, device, templates_loaded, durable}
    POST /api/fingerprint/capture      {timeout}                         -> {template, quality}
    POST /api/fingerprint/enroll       {cliente_id,tenant_id,template1..3}-> {ok, uid}
    POST /api/fingerprint/identify     {tenant_id}                       -> 200 {ok,cliente_id,score} | 404 | 408

Usa ctypes directo a libzkfp.so (NO pyzkfp/Mono — crasheaba en mono_free_lparray). NO hace
pairing/durable (eso es del agente .NET de producción en Windows). Para demo alcanza:
templates en JSON local, matcheo 1:N en el SDK en memoria.

Multi-tenant SIN fuga: cada template tiene un `fid` GLOBAL único; tras el match verifico que
el fid pertenezca al tenant pedido (si no → 404).

Correr:  huella-agent-linux/.venv/bin/python huella-agent-linux/agent.py
"""
import base64
import json
import os
import sys
import threading

# Cargar libs del SDK Linux SOLO para este proceso (LD_LIBRARY_PATH + re-exec una vez).
_SDK_LIB = os.environ.get("ZKFP_LIB_DIR") or os.path.expanduser(
    "~/Downloads/zkfinger-linux-sdk/SDK/lib-x64")
if os.path.isdir(_SDK_LIB) and _SDK_LIB not in os.environ.get("LD_LIBRARY_PATH", "").split(":"):
    cur = os.environ.get("LD_LIBRARY_PATH", "")
    os.environ["LD_LIBRARY_PATH"] = _SDK_LIB + (":" + cur if cur else "")
    os.execv(sys.executable, [sys.executable] + sys.argv)

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zkfp_native import ZKFP, ZKFPError  # noqa: E402

STORE = Path(__file__).with_name("store.json")
API_KEY = os.environ.get("AGENT_API_KEY", "")  # vacío = sin auth (demo localhost)
CAPTURE_DEFAULT_TIMEOUT = 15
POLL_S = 0.2

# ── Store local (un archivo JSON) ────────────────────────────────────────────
# { "next_fid": N, "records": [{fid, tenant_id, cliente_id, template(base64)}] }
_lock = threading.Lock()


def load_store():
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"next_fid": 1, "records": []}


def save_store(s):
    STORE.write_text(json.dumps(s, indent=2))


# ── Device (ctypes / libzkfp.so) ─────────────────────────────────────────────
class Reader:
    def __init__(self):
        self.zk = None
        self.device_name = None

    def open(self):
        zk = ZKFP()
        zk.init()
        if zk.device_count() < 1:
            zk.close()
            raise ZKFPError("0 lectores detectados")
        zk.open(0)
        self.zk = zk
        self.device_name = "ZKTeco SLK20R"
        # Reconstruir la DB en memoria con todos los templates guardados.
        s = load_store()
        for r in s["records"]:
            zk.db_add(r["fid"], base64.b64decode(r["template"]))
        return len(s["records"])

    @property
    def connected(self):
        return self.zk is not None

    def acquire(self, timeout_s):
        """Poll acquire() hasta capturar (bytes) o None si timeout."""
        deadline = time.time() + max(1, timeout_s)
        while time.time() < deadline:
            tmpl = self.zk.acquire()
            if tmpl:
                return tmpl
            time.sleep(POLL_S)
        return None


reader = Reader()
templates_loaded = 0

# ── HTTP ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="HuellaAgent Linux (demo)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # demo: la UI desplegada llama a localhost
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def check_api_key(request: Request, call_next):
    if API_KEY and request.url.path != "/health" and request.method != "OPTIONS":
        if request.headers.get("x-api-key") != API_KEY:
            return JSONResponse({"detail": "api key inválida"}, status_code=401)
    return await call_next(request)


class CaptureReq(BaseModel):
    timeout: int = CAPTURE_DEFAULT_TIMEOUT


class EnrollReq(BaseModel):
    cliente_id: str
    tenant_id: str
    template1: str
    template2: str
    template3: str


class IdentifyReq(BaseModel):
    tenant_id: str


@app.get("/health")
def health():
    return {
        "ok": True,
        "reader": "connected" if reader.connected else "disconnected",
        "device": reader.device_name,
        "templates_loaded": templates_loaded,
        "durable": False,  # demo: sin Supabase
    }


@app.post("/api/fingerprint/capture")
def capture(req: CaptureReq):
    if not reader.connected:
        raise HTTPException(503, "lector no conectado")
    tmpl = reader.acquire(req.timeout)
    if tmpl is None:
        raise HTTPException(408, "no se detectó dedo")
    return {"template": base64.b64encode(tmpl).decode(), "quality": 100}


@app.post("/api/fingerprint/enroll")
def enroll(req: EnrollReq):
    if not reader.connected:
        raise HTTPException(503, "lector no conectado")
    global templates_loaded
    t1 = base64.b64decode(req.template1)
    t2 = base64.b64decode(req.template2)
    t3 = base64.b64decode(req.template3)
    try:
        reg = reader.zk.merge(t1, t2, t3)
    except ZKFPError as e:
        raise HTTPException(400, f"merge falló: {e}")
    with _lock:
        s = load_store()
        fid = s["next_fid"]
        s["next_fid"] = fid + 1
        s["records"].append({
            "fid": fid,
            "tenant_id": req.tenant_id,
            "cliente_id": req.cliente_id,
            "template": base64.b64encode(reg).decode(),
        })
        save_store(s)
        reader.zk.db_add(fid, reg)
        templates_loaded = len(s["records"])
    return {"ok": True, "uid": fid}


@app.post("/api/fingerprint/identify")
def identify(req: IdentifyReq):
    if not reader.connected:
        raise HTTPException(503, "lector no conectado")
    tmpl = reader.acquire(CAPTURE_DEFAULT_TIMEOUT)
    if tmpl is None:
        raise HTTPException(408, "no se detectó dedo")
    result = reader.zk.identify(tmpl)
    if not result:
        raise HTTPException(404, "sin coincidencia")
    fid, score = result
    s = load_store()
    rec = next((r for r in s["records"] if r["fid"] == fid), None)
    # match SOLO si el fid pertenece al tenant pedido (anti-fuga cross-tenant)
    if rec is None or rec["tenant_id"] != req.tenant_id:
        raise HTTPException(404, "sin coincidencia para este tenant")
    return {"ok": True, "cliente_id": rec["cliente_id"], "score": score}


if __name__ == "__main__":
    try:
        n = reader.open()
        templates_loaded = n
        print(f"Lector abierto. {n} templates cargados desde {STORE.name}.")
    except Exception as e:  # noqa: BLE001
        print(f"[ADVERTENCIA] lector no disponible: {e}. /health dirá disconnected.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
