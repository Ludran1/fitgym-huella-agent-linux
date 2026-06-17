#!/usr/bin/env bash
# Instala dependencias del sistema + venv + pyzkfp para el smoke test del SLK20R.
# Corre en Pop!_OS / Ubuntu 24.04. Pide sudo para apt.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"

# NOTA: NO necesita Mono ni pyzkfp. El device se maneja con ctypes (stdlib) directo a
# libzkfp.so. Solo hace falta el venv + fastapi/uvicorn para el agente HTTP.
echo "==> 1/3 apt: python3-venv, libusb-1.0-0"
sudo apt-get update
sudo apt-get install -y python3-venv python3.12-venv python3-full libusb-1.0-0

echo "==> 2/3 venv en $VENV"
# Recrear si no existe o quedó roto (sin binario python por ensurepip faltante).
if [ ! -x "$VENV/bin/python" ]; then
  rm -rf "$VENV"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip

echo "==> 3/3 pip: fastapi, uvicorn (el device va por ctypes, sin pyzkfp)"
"$VENV/bin/pip" install fastapi "uvicorn[standard]"

echo
echo "OK. Siguiente: bash install_sdk.sh <carpeta-lib-x64-del-SDK>"
