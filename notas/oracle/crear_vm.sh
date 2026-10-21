#!/bin/bash
# Crea (o reutiliza) la máquina gratis del monitor de notas en Oracle Cloud y le carga tus datos.
# Se corre en Cloud Shell de Oracle (botón ">_" arriba a la derecha de la consola):
#   bash <(curl -fsSL https://raw.githubusercontent.com/bast727/Prueba-/claude/schedule-app-management-31CF1/notas/oracle/crear_vm.sh)
# Se puede volver a correr sin problema: reutiliza lo que ya exista.
set -euo pipefail

NOMBRE=monitor-notas
C="$OCI_TENANCY"   # compartimento raíz de la cuenta
RAW=https://raw.githubusercontent.com/bast727/Prueba-/claude/schedule-app-management-31CF1/notas/oracle
KEY=~/.ssh/monitor_notas
mkdir -p ~/.ssh
# RSA: Cloud Shell está en modo FIPS y no acepta llaves ED25519.
[ -f "$KEY" ] || ssh-keygen -q -t rsa -b 4096 -N '' -f "$KEY" -C monitor-notas

vacio() { [ -z "$1" ] || [ "$1" = "null" ]; }

echo "== Red"
VCN=$(oci network vcn list -c "$C" --display-name "$NOMBRE-red" --query 'data[0].id' --raw-output 2>/dev/null || true)
if vacio "$VCN"; then
  VCN=$(oci network vcn create -c "$C" --display-name "$NOMBRE-red" --cidr-blocks '["10.20.0.0/16"]' \
        --wait-for-state AVAILABLE --query 'data.id' --raw-output)
  IGW=$(oci network internet-gateway create -c "$C" --vcn-id "$VCN" --is-enabled true --display-name "$NOMBRE-igw" \
        --wait-for-state AVAILABLE --query 'data.id' --raw-output)
  RT=$(oci network vcn get --vcn-id "$VCN" --query 'data."default-route-table-id"' --raw-output)
  oci network route-table update --rt-id "$RT" --force \
    --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" >/dev/null
  oci network subnet create -c "$C" --vcn-id "$VCN" --cidr-block 10.20.0.0/24 --display-name "$NOMBRE-subred" \
    --wait-for-state AVAILABLE >/dev/null
fi
SUBNET=$(oci network subnet list -c "$C" --vcn-id "$VCN" --query 'data[0].id' --raw-output)

echo "== Máquina"
AD=$(oci iam availability-domain list -c "$C" --query 'data[0].name' --raw-output)
INST=$(oci compute instance list -c "$C" --display-name "$NOMBRE" --lifecycle-state RUNNING --query 'data[0].id' --raw-output 2>/dev/null || true)
if vacio "$INST"; then
  curl -fsSL "$RAW/instalar_vm.sh" -o /tmp/instalar_vm.sh
  crear() {  # $1 = forma, $2 = configuración de CPU/RAM (opcional)
    local img
    img=$(oci compute image list -c "$C" --operating-system "Canonical Ubuntu" --operating-system-version "24.04" \
          --shape "$1" --sort-by TIMECREATED --sort-order DESC --query 'data[0].id' --raw-output)
    oci compute instance launch -c "$C" --availability-domain "$AD" --display-name "$NOMBRE" \
      --shape "$1" ${2:+--shape-config "$2"} --image-id "$img" --subnet-id "$SUBNET" --assign-public-ip true \
      --ssh-authorized-keys-file "$KEY.pub" --user-data-file /tmp/instalar_vm.sh \
      --wait-for-state RUNNING --query 'data.id' --raw-output
  }
  echo "Creando la máquina gratis (Ampere A1: 1 CPU, 6 GB)..."
  INST=$(crear VM.Standard.A1.Flex '{"ocpus":1,"memoryInGBs":6}') || {
    echo "No hay capacidad A1 en Santiago ahora; probando la máquina gratis E2.1.Micro..."
    INST=$(crear VM.Standard.E2.1.Micro '')
  }
fi
IP=$(oci compute instance list-vnics --instance-id "$INST" --query 'data[0]."public-ip"' --raw-output)
echo "IP pública: $IP"
SSH="ssh -i $KEY -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 ubuntu@$IP"

echo "== Esperando que la máquina acepte conexiones"
until $SSH true 2>/dev/null; do sleep 10; done
echo "== Esperando que termine la instalación (5 a 15 minutos)"
$SSH 'sudo cloud-init status --wait' >/dev/null || true
if ! $SSH 'test -f /opt/monitor-notas/INSTALACION_OK'; then
  echo "La instalación falló. Últimas líneas del registro:"
  $SSH 'sudo tail -n 40 /var/log/monitor-notas-instalacion.log'
  exit 1
fi

echo "== Prueba de conexión al portal desde Chile"
$SSH 'curl -s -o /dev/null -m 20 -w "portal.ucsc.cl -> %{http_code} en %{time_total}s\n" https://portal.ucsc.cl/alumno || echo "portal.ucsc.cl -> sin respuesta"'

if ! $SSH 'sudo test -s /etc/monitor-notas.env'; then
  echo
  echo "== Tus datos (quedan solo en esta máquina; la contraseña no se ve mientras escribes)"
  read -rp "RUT sin puntos ni dígito verificador: " RUT
  read -rsp "Contraseña del portal UCSC: " PASS; echo
  read -rp "Canal de ntfy (el mismo de NTFY_TOPIC en GitHub): " TOPIC
  printf 'UCSC_RUT=%q\nUCSC_PASSWORD=%q\nNTFY_TOPIC=%q\n' "$RUT" "$PASS" "$TOPIC" \
    | $SSH 'sudo tee /etc/monitor-notas.env >/dev/null'
  unset RUT PASS TOPIC
fi

echo "== Primera revisión (1 a 3 minutos)"
$SSH 'sudo systemctl start monitor-notas.service' || true
$SSH 'sudo journalctl -u monitor-notas.service -n 15 --no-pager -o cat'
$SSH 'systemctl list-timers monitor-notas.timer --no-pager'
echo
echo "LISTO: la máquina revisa el portal cada 15 minutos."
