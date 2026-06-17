#!/usr/bin/env python3
"""
Agente de huella LINUX para DEMOS portátiles (laptop Linux + SLK20R via libzkfp.so nativo).

Sirve el MISMO contrato HTTP que el frontend (src/lib/huellaApi.ts):
    GET  /health                       -> {ok, reader, device, templates_loaded, durable}
    POST /api/fingerprint/capture      {timeout}                          -> {template, quality}
    POST /api/fingerprint/enroll       {cliente_id,tenant_id,template1..3} -> {ok, uid}
    POST /api/fingerprint/identify     {tenant_id}                         -> 200 {ok,cliente_id,score} | 404 | 408
    POST /api/pair                     {token,supabase_url,anon_key}       -> {ok, tenant_id, gym, templates}

Device por ctypes (zkfp_native, sin Mono/pyzkfp). DURABLE opcional (huella_rpc): si está
vinculado (pairing.json), espeja el enroll a Supabase vía huella_enroll (→ setea
clientes.huella_registered=true, el front muestra "Registrada") y al arrancar recarga los
templates del tenant con huella_templates. Sin vincular = solo store.json local (demo).

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
import huella_rpc as rpc  # noqa: E402

STORE = Path(__file__).with_name("store.json")
API_KEY = os.environ.get("AGENT_API_KEY", "")  # vacío = sin auth (demo localhost)
CAPTURE_DEFAULT_TIMEOUT = 15
POLL_S = 0.2
_lock = threading.Lock()


# ── Store local (JSON): {records: [{fid, tenant_id, cliente_id, template(base64)}]} ──
def load_store():
    if STORE.exists():
        s = json.loads(STORE.read_text())
        s.setdefault("records", [])
        return s
    return {"records": []}


def save_store(s):
    STORE.write_text(json.dumps(s, indent=2))


# ── Device (ctypes / libzkfp.so) + durable opcional ──────────────────────────
class Reader:
    def __init__(self):
        self.zk = None
        self.device_name = None
        self.creds = None  # pairing → durable
        self.count = 0

    @property
    def connected(self):
        return self.zk is not None

    @property
    def durable(self):
        return self.creds is not None

    def open(self):
        zk = ZKFP()
        zk.init()
        if zk.device_count() < 1:
            zk.close()
            raise ZKFPError("0 lectores detectados")
        zk.open(0)
        self.zk = zk
        self.device_name = "ZKTeco SLK20R"
        self.creds = rpc.load_creds()
        self.reload()
        return self.count

    def reload(self):
        """Reconstruye la DB en memoria: si es durable, baja los templates del tenant de
        Supabase (fuente de verdad) y los espeja en store.json; siempre carga store.json."""
        s = load_store()
        if self.creds:
            res = rpc.templates(self.creds)
            if res:
                tid, tmpls = res
                # Supabase manda para ese tenant: reemplazá sus records locales.
                s["records"] = [r for r in s["records"] if r["tenant_id"] != tid]
                for t in tmpls:
                    s["records"].append({
                        "fid": t["uid"], "tenant_id": tid,
                        "cliente_id": t["cliente_id"], "template": t["template"]})
                save_store(s)
        with _lock:
            self.zk.db_clear()
            for r in s["records"]:
                self.zk.db_add(r["fid"], base64.b64decode(r["template"]))
        self.count = len(s["records"])

    def acquire(self, timeout_s):
        deadline = time.time() + max(1, timeout_s)
        while time.time() < deadline:
            tmpl = self.zk.acquire()
            if tmpl:
                return tmpl
            time.sleep(POLL_S)
        return None

    def enroll(self, tenant_id, cliente_id, reg_bytes):
        """Guarda el template merged. Durable → huella_enroll (uid server-side, setea
        huella_registered). Local → uid existente del cliente o max+1. Upsert por cliente."""
        reg_b64 = base64.b64encode(reg_bytes).decode()
        with _lock:
            s = load_store()
            prev = next((r for r in s["records"]
                         if r["tenant_id"] == tenant_id and r["cliente_id"] == cliente_id), None)
            if self.creds:
                uid = rpc.enroll(self.creds, cliente_id, reg_b64)
                if uid is None:
                    raise ZKFPError("huella_enroll (durable) falló")
            else:
                uid = prev["fid"] if prev else (max([r["fid"] for r in s["records"]], default=0) + 1)
            # upsert local por (tenant, cliente)
            s["records"] = [r for r in s["records"]
                            if not (r["tenant_id"] == tenant_id and r["cliente_id"] == cliente_id)]
            s["records"].append({"fid": uid, "tenant_id": tenant_id,
                                 "cliente_id": cliente_id, "template": reg_b64})
            save_store(s)
            self.zk.db_del(uid)       # re-enroll: saca el viejo fid antes de re-agregar
            self.zk.db_add(uid, reg_bytes)
            self.count = len(s["records"])
        return uid

    def pair(self, token, supabase_url, anon_key):
        info = rpc.validate(token, supabase_url, anon_key)
        if not info:
            raise ZKFPError("token inválido (kiosk_init falló)")
        rpc.save_creds(token, supabase_url, anon_key)
        self.creds = rpc.load_creds()
        self.reload()   # baja templates del tenant
        return info, self.count


reader = Reader()

# ── HTTP ─────────────────────────────────────────────────────────────────────
app = FastAPI(title="HuellaAgent Linux (demo)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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


class PairReq(BaseModel):
    token: str
    supabase_url: str
    anon_key: str


@app.get("/health")
def health():
    return {
        "ok": True,
        "reader": "connected" if reader.connected else "disconnected",
        "device": reader.device_name,
        "templates_loaded": reader.count,
        "durable": reader.durable,
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
    t1 = base64.b64decode(req.template1)
    t2 = base64.b64decode(req.template2)
    t3 = base64.b64decode(req.template3)
    try:
        reg = reader.zk.merge(t1, t2, t3)
        uid = reader.enroll(req.tenant_id, req.cliente_id, reg)
    except ZKFPError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "uid": uid}


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
    rec = next((r for r in load_store()["records"] if r["fid"] == fid), None)
    if rec is None or rec["tenant_id"] != req.tenant_id:
        raise HTTPException(404, "sin coincidencia para este tenant")
    return {"ok": True, "cliente_id": rec["cliente_id"], "score": score}


@app.post("/api/pair")
def pair(req: PairReq):
    if not reader.connected:
        raise HTTPException(503, "lector no conectado")
    try:
        info, n = reader.pair(req.token, req.supabase_url, req.anon_key)
    except ZKFPError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "tenant_id": info["tenant_id"], "gym": info["gym"], "templates": n}


if __name__ == "__main__":
    try:
        n = reader.open()
        d = "DURABLE (vinculado)" if reader.durable else "local (demo, sin pairing)"
        print(f"Lector abierto. {n} templates cargados. Modo: {d}.")
    except Exception as e:  # noqa: BLE001
        print(f"[ADVERTENCIA] lector no disponible: {e}. /health dirá disconnected.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
