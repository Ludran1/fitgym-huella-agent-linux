#!/usr/bin/env bash
# Verifica el ZKFinger Linux SDK (NO copia nada al sistema: las libs se cargan aisladas
# via LD_LIBRARY_PATH desde smoke_test.py / agent.py). Sin sudo.
# Uso: bash install_sdk.sh [carpeta-lib-x64]   (default: ~/Downloads/zkfinger-linux-sdk/SDK/lib-x64)
set -euo pipefail

LIB="${1:-$HOME/Downloads/zkfinger-linux-sdk/SDK/lib-x64}"

echo "==> Carpeta de libs: $LIB"
if [ ! -d "$LIB" ]; then
  echo "No existe. Pasá la ruta de lib-x64 del SDK Linux descomprimido." >&2
  exit 1
fi
if [ ! -f "$LIB/libzkfp.so" ]; then
  echo "No veo libzkfp.so en $LIB. ¿Es la carpeta lib-x64 correcta?" >&2
  ls -1 "$LIB" >&2
  exit 1
fi

echo "==> libs presentes:"; ls -1 "$LIB"

echo; echo "==> Dependencias de libzkfp.so (con LD_LIBRARY_PATH=$LIB):"
LD_LIBRARY_PATH="$LIB:${LD_LIBRARY_PATH:-}" ldd "$LIB/libzkfp.so" || true

echo; echo "==> 'not found' arriba = falta esa lib. Las del SDK + del sistema deberían"
echo "    resolver todo. Si falta alguna del sistema (ej. libnuma), instalala con apt."
echo "==> OK. No hace falta copiar nada: smoke_test.py y agent.py ya usan ZKFP_LIB_DIR=$LIB"
