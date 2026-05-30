#!/usr/bin/env bash
# ============================================================
#  instalar_en_servidor.sh
#  Instalador todo-en-uno para un servidor Ubuntu nuevo
#  (DigitalOcean). Deja el radar funcionando cada 30 min.
#
#  Uso (dentro del servidor):
#    bash instalar_en_servidor.sh
# ============================================================
set -e

echo ""
echo "==================================================="
echo "  Instalando el Radar de Coches en el servidor..."
echo "==================================================="
echo ""

# 1) Paquetes del sistema
echo "[1/6] Actualizando el sistema e instalando Python..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-pip python3-venv unzip curl

# 2) Dependencias que necesita el navegador Chromium
echo "[2/6] Instalando librerias para el navegador..."
apt-get install -y libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libgbm1 libasound2 libatspi2.0-0 libwayland-client0 || true

# 3) Carpeta de trabajo y entorno Python aislado
echo "[3/6] Preparando el programa..."
mkdir -p /opt/radar
cd /opt/radar
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install playwright requests

# 4) Navegador para Playwright
echo "[4/6] Descargando el navegador (puede tardar un par de minutos)..."
./venv/bin/python -m playwright install chromium
./venv/bin/python -m playwright install-deps chromium || true

# 4b) Meter el numero y apikey de WhatsApp en el config
# (se pasan al ejecutar:  WA_PHONE=+34... WA_KEY=... bash instalar_en_servidor.sh)
if [ -n "$WA_PHONE" ] && [ -n "$WA_KEY" ]; then
  echo "    Configurando tu WhatsApp..."
  python3 - "$WA_PHONE" "$WA_KEY" <<'PY'
import json, sys
p = "/opt/radar/config.json"
c = json.load(open(p))
c["notificaciones"]["whatsapp"] = {"enabled": True, "phone": sys.argv[1], "apikey": sys.argv[2]}
json.dump(c, open(p, "w"), ensure_ascii=False, indent=2)
print("    WhatsApp configurado para", sys.argv[1])
PY
else
  echo "    (No se han pasado datos de WhatsApp; los pondras a mano luego)"
fi

# 5) Servicio que mantiene el radar corriendo siempre
echo "[5/6] Configurando el arranque automatico..."
cat > /etc/systemd/system/radar.service <<'UNIT'
[Unit]
Description=Radar de Coches
After=network-online.target

[Service]
WorkingDirectory=/opt/radar
ExecStart=/opt/radar/venv/bin/python /opt/radar/radar.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable radar.service
systemctl restart radar.service

# 6) Mensaje de prueba al arrancar
echo "[6/6] Listo."
echo ""
echo "==================================================="
echo "  INSTALACION COMPLETADA"
echo "  El radar ya esta funcionando y buscara cada 30 min."
echo ""
echo "  Para ver que esta haciendo en directo:"
echo "    journalctl -u radar.service -f"
echo ""
echo "  Para pararlo:   systemctl stop radar.service"
echo "  Para arrancarlo: systemctl start radar.service"
echo "==================================================="
