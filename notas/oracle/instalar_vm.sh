#!/bin/bash
# Instala el monitor de notas en una máquina Ubuntu de Oracle Cloud (Santiago).
# Lo ejecuta cloud-init al crear la máquina (lo usa crear_vm.sh); no lleva datos personales.
# El portal UCSC solo responde a conexiones desde Chile, por eso corre aquí y no en GitHub.
set -euxo pipefail
exec > /var/log/monitor-notas-instalacion.log 2>&1

# 2 GB de swap: la máquina gratis más chica tiene 1 GB de RAM y Chromium necesita más.
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

export DEBIAN_FRONTEND=noninteractive
APT="apt-get -o DPkg::Lock::Timeout=900"
$APT update
$APT install -y git python3-venv curl

id monitor >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/monitor-notas monitor
rm -rf /opt/monitor-notas
git clone --depth 1 --branch claude/schedule-app-management-31CF1 https://github.com/bast727/Prueba-.git /opt/monitor-notas
python3 -m venv /opt/monitor-notas/venv
/opt/monitor-notas/venv/bin/pip install -r /opt/monitor-notas/notas/requirements.txt
PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright /opt/monitor-notas/venv/bin/playwright install --with-deps chromium
chmod -R a+rX /opt/ms-playwright /opt/monitor-notas
install -d -o monitor -g monitor -m 700 /var/lib/monitor-notas/estado

# Tus datos los carga crear_vm.sh después; solo root y el usuario "monitor" pueden leerlos.
touch /etc/monitor-notas.env
chown root:monitor /etc/monitor-notas.env
chmod 640 /etc/monitor-notas.env

cat > /etc/systemd/system/monitor-notas.service <<'EOF'
[Unit]
Description=Monitor de notas UCSC (una revisión)
Wants=network-online.target
After=network-online.target
ConditionFileNotEmpty=/etc/monitor-notas.env

[Service]
Type=oneshot
User=monitor
WorkingDirectory=/opt/monitor-notas
Environment=ESTADO_PATH=/var/lib/monitor-notas/estado/avisos.json
Environment=PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
ExecStart=/bin/bash -c 'set -a; . /etc/monitor-notas.env; set +a; exec /opt/monitor-notas/venv/bin/python notas/revisar_notas.py'
# Salida 2 = el portal rechazó la contraseña: se apaga solo para no bloquear la cuenta
# (el portal bloquea tras 6 intentos fallidos).
ExecStopPost=+/bin/sh -c 'if [ "$EXIT_STATUS" = "2" ]; then systemctl disable --now monitor-notas.timer; fi'
TimeoutStartSec=12min
EOF

cat > /etc/systemd/system/monitor-notas.timer <<'EOF'
[Unit]
Description=Revisar notas UCSC cada 15 minutos

[Timer]
OnCalendar=*:0/15
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now monitor-notas.timer
touch /opt/monitor-notas/INSTALACION_OK
