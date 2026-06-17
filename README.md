# Huella SLK20R — smoke test en laptop Linux (Pop!_OS / Ubuntu 24.04)

Objetivo: probar que el lector **ZKTeco SLK20R** captura, enrola e identifica huellas
en TU laptop Linux, para hacer demos en negocios. Esto **no** es el agente de producción
todavía — es la validación de hardware + SDK antes de invertir en el agente .NET 8.

Cadena de dependencias (VALIDADA 2026-06-17):
Python **ctypes** (stdlib) → `libzkfp.so` (API C nativa del **ZKFinger Linux SDK**).
**NO usa Mono ni pyzkfp** (pyzkfp crasheaba en Mono: `mono_free_lparray` al marshallar
los arrays de AcquireFingerprint, sin fix ni en Mono 6.12). ctypes llama la API C directo.

---

## Orden de pasos

### 0. (Solo vos) Bajar el ZKFinger Linux SDK
Requiere cuenta ZKTeco. Página: https://www.zkteco.com/en/Biometrics_Module_SDK/ZKFinger-SDK-for-Linux
Descargá el SDK Linux (tar/zip). Adentro vienen los `.so` (`libzkfp.so` + deps en
`SDK/lib-x64`) + demos en C y Java. Descomprimí, p.ej. en `~/Downloads/zkfinger-linux-sdk/`.

### 1. Instalar dependencias del sistema (sudo)
```bash
bash huella-agent-linux/setup.sh
```
Instala: `python3-venv`, `libusb-1.0-0`. Crea el venv `.venv` + instala fastapi/uvicorn.
El device va por ctypes (stdlib) → NO instala Mono ni pyzkfp.

### 2. Verificar el SDK Linux (sin sudo, NO copia nada)
```bash
bash huella-agent-linux/install_sdk.sh ~/Downloads/zkfinger-linux-sdk/SDK/lib-x64
```
NO copia libs al sistema (evita pisar libsqlite3/libcrypto). Solo confirma que
`libzkfp.so` + sus dependencias resuelven. Las libs se cargan AISLADAS en runtime via
`LD_LIBRARY_PATH` (smoke_test.py y agent.py ya lo hacen, default
`~/Downloads/zkfinger-linux-sdk/SDK/lib-x64`; override con `ZKFP_LIB_DIR=...`).

### 3. Enchufar el SLK20R y detectar VID:PID + regla udev (sudo)
```bash
bash huella-agent-linux/detect_reader.sh
```
Hace diff de `lsusb` antes/después de enchufar, detecta el VID:PID del lector,
y escribe `/etc/udev/rules.d/99-zkfinger.rules` con `MODE=0666` (acceso sin root).
Después: desenchufá y volvé a enchufar el lector para que aplique la regla.

### 4. Smoke test (probe de hardware aislado)
```bash
huella-agent-linux/.venv/bin/python huella-agent-linux/smoke_test.py
```
Flujo: Init → cuenta dispositivos → OpenDevice → enrola (3 capturas del mismo dedo)
→ DBMerge → DBAdd → pide otra huella → DBIdentify → imprime fid + score. Si ves
`MATCH fid=1 score=...` funciona la cadena completa. Prueba que el lector LEE en Linux.
(Init/OpenDevice/AcquireFingerprint ya validados sin crash 2026-06-17; falta solo el dedo.)

### 5. Agente demo (sirve el contrato HTTP a la UI desplegada)
```bash
huella-agent-linux/.venv/bin/python huella-agent-linux/agent.py
```
Levanta el agente en `http://localhost:8000` con los 4 endpoints que ya consume el
frontend (`/health`, `/api/fingerprint/{capture,enroll,identify}`). Con esto, en el
navegador de la laptop abrís el SaaS desplegado (`www.fitgym-app.com`, ya tiene
`VITE_HUELLA_ENABLED=true` + CSP `connect-src http://localhost:8000`) y hacés el demo
REAL: enrolar desde la ficha del cliente → kiosko identifica → marca asistencia.
Por defecto local (`store.json`, `durable:false`). Para que el enroll PERSISTA + el front
muestre "Registrada" al recargar: tocá **"Vincular lector"** en la UI (Configuración) → el
agente se vincula (`/api/pair`) y espeja a Supabase (`huella_enroll`). Ver `huella_rpc.py`.

---

## Troubleshooting
- `device_count() == 0`: lector no detectado. Revisá `lsusb` + la regla udev (paso 3).
- `OSError: libzkfp.so: cannot open shared object`: `ZKFP_LIB_DIR` mal o SDK no descomprimido
  → corré `install_sdk.sh <lib-x64>` (verifica deps). Default `~/Downloads/zkfinger-linux-sdk/SDK/lib-x64`.
- Permiso denegado al abrir el device: la regla udev no aplicó → desenchufá/enchufá, o
  `sudo udevadm control --reload-rules && sudo udevadm trigger`.
- Segfault en AcquireFingerprint: era pyzkfp/Mono (YA NO se usa). Si reaparece, revisá que
  `zkfp_native.py` tenga `restype=c_void_p` en los handles (truncar el puntero = crash).

## Contexto: por qué ctypes y no el agente .NET ni pyzkfp
El agente de PRODUCCIÓN es .NET 8 (repo `fitgym-huella-agent`) y ya está LIVE en la PC
Windows del gym (enroll→identify→asistencia probado, pairing + durable + auto-update). Este
kit es SOLO para **demos portátiles en tu laptop Linux**. El SDK Linux trae solo libs C/Java
(NO wrapper C#) → portar el .NET era inviable. `pyzkfp` (Python+Mono) crasheaba. Solución:
**ctypes directo a `libzkfp.so`** (`zkfp_native.py`) → cero runtime extra, robusto. Para demos
no hace falta durable/pairing → `agent.py` (FastAPI + ctypes + `store.json`) reusa el contrato
del frontend tal cual. Producción Windows queda intacta.
