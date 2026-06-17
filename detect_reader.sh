#!/usr/bin/env bash
# Detecta el VID:PID del SLK20R por diff de lsusb (desenchufado -> enchufado)
# y escribe una regla udev para acceso sin root.
set -euo pipefail

RULE=/etc/udev/rules.d/99-zkfinger.rules

echo "==> Paso 1: DESENCHUFÁ el lector SLK20R. Luego ENTER."
read -r _
BEFORE="$(lsusb | sort)"

echo "==> Paso 2: ENCHUFÁ el lector ahora. Esperá 2s y ENTER."
read -r _
AFTER="$(lsusb | sort)"

NEW="$(comm -13 <(echo "$BEFORE") <(echo "$AFTER") || true)"
if [ -z "$NEW" ]; then
  echo "No detecté ningún dispositivo nuevo. ¿Quedó enchufado? lsusb actual:" >&2
  lsusb
  exit 1
fi

echo "==> Dispositivo nuevo detectado:"
echo "    $NEW"

# Extrae el primer VID:PID de la línea nueva (formato: ID xxxx:yyyy ...)
IDPAIR="$(echo "$NEW" | grep -oE 'ID [0-9a-fA-F]{4}:[0-9a-fA-F]{4}' | head -1 | awk '{print $2}')"
VID="${IDPAIR%%:*}"
PID="${IDPAIR##*:}"
if [ -z "$VID" ] || [ -z "$PID" ]; then
  echo "No pude parsear VID:PID de: $NEW" >&2
  exit 1
fi
echo "    VID=$VID  PID=$PID"

echo "==> Escribiendo $RULE (sudo)"
sudo tee "$RULE" >/dev/null <<EOF
# ZKTeco SLK20R fingerprint reader — acceso sin root
SUBSYSTEM=="usb", ATTRS{idVendor}=="$VID", ATTRS{idProduct}=="$PID", MODE="0666", GROUP="plugdev"
EOF

echo "==> Recargando udev"
sudo udevadm control --reload-rules
sudo udevadm trigger

echo
echo "OK. Regla escrita para $VID:$PID."
echo "IMPORTANTE: desenchufá y volvé a enchufar el lector para que aplique."
