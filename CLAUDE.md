# CLAUDE.md — Instrucciones para el agente

Este repo es el **agente de huella SLK20R para demos en laptop Linux**. Si sos un agente
de Claude Code abriendo este repo en una laptop Linux nueva, tu objetivo es: **dejar el
lector ZKTeco SLK20R funcionando** para hacer una demo del SaaS fitgym (enrolar huella →
identificar → marcar asistencia) usando la UI desplegada en el navegador.

## Contexto (leé antes de tocar nada)
- El agente de **producción** es .NET 8 (repo aparte `fitgym-huella-agent`), corre en Windows
  en el gym y ya está LIVE. **Esto NO es eso.** Esto es un agente Python aparte, SOLO para
  demos portátiles en una laptop Linux. No toca producción.
- Sirve el MISMO contrato HTTP que consume el frontend, en `http://localhost:8000`:
  - `GET  /health` → `{ok, reader:"connected"|"disconnected", device, templates_loaded, durable}`
  - `POST /api/fingerprint/capture` `{timeout}` → `{template(base64), quality}`
  - `POST /api/fingerprint/enroll` `{cliente_id,tenant_id,template1,template2,template3}` → `{ok,uid}`
  - `POST /api/fingerprint/identify` `{tenant_id}` → 200 `{ok,cliente_id,score}` / 404 / 408
- La UI desplegada `www.fitgym-app.com` ya tiene `VITE_HUELLA_ENABLED=true` + CSP
  `connect-src http://localhost:8000`. `http://localhost` desde `https` funciona (Secure
  Context). Con el agente corriendo, la UI muestra "Lector conectado" y deja enrolar/identificar.

## Decisiones de arquitectura YA TOMADAS (no las repitas)
- **El device se maneja con `ctypes` directo a `libzkfp.so`** (ver `zkfp_native.py`).
- ❌ **NO uses `pyzkfp`.** Bindea el wrapper C# vía pythonnet+Mono → **SIGSEGV en
  `mono_free_lparray`** al marshallar los arrays de `AcquireFingerprint`. Pasa en Mono 6.8
  Y 6.12 (no es la versión de Mono — es la capa de marshalling). No instales Mono.
- ❌ **NO intentes portar el agente .NET a Linux.** El ZKFinger Linux SDK trae solo libs
  C + Java (NO wrapper C#) → no hay nada que referenciar.
- ⚠️ En `zkfp_native.py`, los handles (`ZKFPM_OpenDevice`/`ZKFPM_DBInit`) DEBEN tener
  `restype = c_void_p`. Si los dejás como int, ctypes trunca el puntero a 32-bit → segfault.

## Lo que necesita el HUMANO (no lo podés hacer vos)
1. **Bajar el ZKFinger Linux SDK** de https://www.zkteco.com/en/Biometrics_Module_SDK/ZKFinger-SDK-for-Linux
   (requiere cuenta ZKTeco). Es propietario → NO está en este repo. Descomprimir en
   `~/Downloads/zkfinger-linux-sdk/` (queda `~/Downloads/zkfinger-linux-sdk/SDK/lib-x64/libzkfp.so`).
   Si lo pone en otro lado, usar `ZKFP_LIB_DIR=/ruta/a/lib-x64`.
2. **`sudo` pide password** → los pasos con apt/udev los corre el humano (o lo guiás a que
   pegue `! bash setup.sh` etc.). Vos no podés tipear el password.
3. **Enchufar el SLK20R** (USB).
4. **Apoyar el dedo** en el smoke test / enroll (3 capturas + 1 para identificar).

## Pasos (en orden)
```bash
bash setup.sh                                              # venv + fastapi/uvicorn (sudo apt)
bash install_sdk.sh ~/Downloads/zkfinger-linux-sdk/SDK/lib-x64   # verifica libzkfp.so + deps (sin sudo)
bash detect_reader.sh                                     # plug reader → udev rule (sudo); reenchufar al final
.venv/bin/python smoke_test.py                            # humano apoya dedo → "MATCH fid=1 score=..."
.venv/bin/python agent.py                                 # demo: dejar corriendo + abrir www.fitgym-app.com
```

## Cómo verificar éxito (sin depender del humano para cada chequeo)
- Hardware/SDK OK: `smoke_test.py` imprime `device_count`≥1 + `OpenDevice OK imagen 300x400`
  + `AcquireFingerprint` poolea sin segfault. (Esto ya se validó; si crashea, revisá
  `restype=c_void_p` y `ZKFP_LIB_DIR`.)
- Agente OK: arrancá `agent.py`, luego
  `curl -s --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:8000/health`
  debe dar `{"ok":true,"reader":"connected","device":"ZKTeco SLK20R",...}`.
- Demo completa: solo el humano (apoyar dedo en la UI). Necesita el login del gym en
  www.fitgym-app.com + un cliente para enrolar.

## Archivos
- `zkfp_native.py` — wrapper ctypes de `libzkfp.so` (Init/OpenDevice/Acquire/DBMerge/DBAdd/DBIdentify).
- `agent.py` — FastAPI localhost:8000, contrato del frontend, store en `store.json` local,
  multi-tenant por `fid` global único + chequeo de `tenant_id` post-match (anti fuga), CORS abierto.
- `smoke_test.py` — prueba aislada del lector (sin SaaS).
- `setup.sh` / `install_sdk.sh` / `detect_reader.sh` — instalación/verificación/permisos.
- `README.md` — la versión human-readable de todo esto.

## Entorno validado
Pop!_OS 24.04 (Ubuntu base), x86_64, Python 3.12. Para demo NO hace falta durable/pairing
(eso es del agente .NET de producción). Acá los templates viven en `store.json` local.
