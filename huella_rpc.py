"""
Persistencia DURABLE vía RPCs SECURITY DEFINER (anon key pública + kiosk_token), igual que
el agente .NET de prod (Supabase/HuellaRpc.cs). NUNCA service-role.

RPCs (definidas en supabase/migrations/20260615120000_huella_rpcs.sql):
  kiosk_init(p_token)        -> {ok, tenant_id, gym_nombre}     (validar pairing)
  huella_enroll(p_token, p_cliente_id, p_template) -> {ok, uid} (upsert + huella_registered=true)
  huella_templates(p_token)  -> {ok, tenant_id, templates:[{cliente_id, uid, template}]}

Las credenciales del pairing viven en pairing.json (plano — laptop de demo; el .NET usa DPAPI
en Windows / plano en Linux). Sin dependencias extra: urllib stdlib.
"""
import json
import urllib.request
from pathlib import Path

PAIRING = Path(__file__).with_name("pairing.json")


def load_creds():
    """Credenciales activas o None. {token, supabase_url, anon_key}."""
    if PAIRING.exists():
        d = json.loads(PAIRING.read_text())
        if d.get("token") and d.get("supabase_url") and d.get("anon_key"):
            return d
    return None


def save_creds(token, supabase_url, anon_key):
    PAIRING.write_text(json.dumps(
        {"token": token, "supabase_url": supabase_url, "anon_key": anon_key}, indent=2))


def _rpc(creds, fn, body, timeout=10):
    url = creds["supabase_url"].rstrip("/") + "/rest/v1/rpc/" + fn
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={
            "Content-Type": "application/json",
            "apikey": creds["anon_key"],
            "Authorization": "Bearer " + creds["anon_key"],
        })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or "{}")


def validate(token, supabase_url, anon_key):
    """kiosk_init → {tenant_id, gym} o None si el token no sirve."""
    creds = {"token": token, "supabase_url": supabase_url, "anon_key": anon_key}
    try:
        d = _rpc(creds, "kiosk_init", {"p_token": token})
    except Exception:  # noqa: BLE001
        return None
    if not d.get("ok"):
        return None
    return {"tenant_id": d.get("tenant_id"), "gym": d.get("gym_nombre")}


def enroll(creds, cliente_id, template_b64):
    """huella_enroll → uid (server-side) o None."""
    try:
        d = _rpc(creds, "huella_enroll", {
            "p_token": creds["token"], "p_cliente_id": cliente_id, "p_template": template_b64})
    except Exception:  # noqa: BLE001
        return None
    return d.get("uid") if d.get("ok") else None


def templates(creds):
    """huella_templates → (tenant_id, [{cliente_id, uid, template}]) o None."""
    try:
        d = _rpc(creds, "huella_templates", {"p_token": creds["token"]})
    except Exception:  # noqa: BLE001
        return None
    if not d.get("ok") or not d.get("tenant_id"):
        return None
    return d["tenant_id"], (d.get("templates") or [])
