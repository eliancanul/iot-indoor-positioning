#!/bin/bash
# ============================================================
#  CONFIGURACIÓN MQTTS EN RASPBERRY PI — Proyecto IoT UQROO
# ============================================================
#  Configura Mosquitto con TLS (puerto 8883), genera certificados
#  autofirmados y crea un usuario MQTT.
#
#  USO:
#    1. Copiar este archivo a la Raspberry Pi (ej. por SCP)
#    2. Editar las variables en la sección CONFIGURACIÓN
#    3. Ejecutar:  sudo bash setup_mqtts.sh
#
#  El script es IDEMPOTENTE: puede ejecutarse múltiples veces.
# ============================================================

set -e

# -------------------- CONFIGURACIÓN --------------------
# ⚙️ EDITA ESTOS VALORES ANTES DE EJECUTAR

MQTT_USER="usuario_raspberry"
MQTT_PASS="${MQTT_PASS:?Set MQTT_PASS in the environment before running this script}"
BROKER_IP="192.168.2.2"
COUNTRY="MX"
STATE="Quintana Roo"
CITY="Chetumal"
ORG="UQROO"
CERT_DAYS="3650"  # 10 años

# -------------------------------------------------------

CERT_DIR="/etc/mosquitto/certs"
PASSWD_FILE="/etc/mosquitto/passwd"
CONF_FILE="/etc/mosquitto/conf.d/mqtts.conf"

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
print_info() { echo -e "${BLUE}[i]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
print_step() { echo -e "\n${BLUE}════════════════════════════════════════${NC}"
               echo -e "${BLUE}  $1${NC}"
               echo -e "${BLUE}════════════════════════════════════════${NC}"; }

echo -e "${GREEN}"
echo "============================================================"
echo "  CONFIGURACIÓN MQTTS — Sistema IoT UQROO"
echo "============================================================"
echo -e "${NC}"

# Verificar root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR] Este script debe ejecutarse como root.${NC}"
    echo -e "  Ejecuta: ${YELLOW}sudo bash setup_mqtts.sh${NC}"
    exit 1
fi

# ------------------------------------------------------------
# PASO 1: Instalar dependencias
# ------------------------------------------------------------
print_step "PASO 1: Instalando dependencias"

if command -v mosquitto &> /dev/null; then
    print_ok "Mosquitto ya está instalado"
else
    print_info "Instalando Mosquitto y OpenSSL..."
    apt-get update -qq
    apt-get install -y mosquitto mosquitto-clients openssl
    print_ok "Mosquitto instalado correctamente"
fi

# ------------------------------------------------------------
# PASO 2: Generar certificados autofirmados
# ------------------------------------------------------------
print_step "PASO 2: Generando certificados (Broker IP: ${BROKER_IP})"

mkdir -p "${CERT_DIR}"
cd "${CERT_DIR}"

# Respaldar si ya existían
if [ -f "ca.key" ] || [ -f "ca.crt" ]; then
    BACKUP_DIR="${CERT_DIR}/backup_$(date +%Y%m%d_%H%M%S)"
    print_warn "Ya existen certificados. Respaldando en ${BACKUP_DIR}"
    mkdir -p "${BACKUP_DIR}"
    cp ca.key ca.crt server.key server.crt server.csr "${BACKUP_DIR}/" 2>/dev/null || true
    rm -f ca.key ca.crt ca.srl server.key server.crt server.csr
fi

# Generar CA (Autoridad Certificadora local)
print_info "Generando CA..."
openssl genrsa -out ca.key 2048 2>/dev/null
openssl req -new -x509 -days "${CERT_DAYS}" -key ca.key -out ca.crt \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/CN=IoT-UQROO-CA" 2>/dev/null

# Generar certificado del servidor (broker)
print_info "Generando certificado del servidor..."
openssl genrsa -out server.key 2048 2>/dev/null
openssl req -new -key server.key -out server.csr \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/CN=${BROKER_IP}" 2>/dev/null

# Firmar el certificado del servidor con la CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days "${CERT_DAYS}" 2>/dev/null

# Permisos
chmod 600 *.key
chmod 644 *.crt
cd - > /dev/null

print_ok "Certificados generados en ${CERT_DIR}"
echo -e "  ${YELLOW}Copia ca.crt al ESP32 y al Windows${NC}"

# ------------------------------------------------------------
# PASO 3: Crear usuario MQTT
# ------------------------------------------------------------
print_step "PASO 3: Configurando usuario MQTT"

if [ -f "${PASSWD_FILE}" ]; then
    print_info "Actualizando usuario '${MQTT_USER}'..."
    mosquitto_passwd -b "${PASSWD_FILE}" "${MQTT_USER}" "${MQTT_PASS}"
else
    print_info "Creando usuario '${MQTT_USER}'..."
    mosquitto_passwd -b -c "${PASSWD_FILE}" "${MQTT_USER}" "${MQTT_PASS}"
fi

print_ok "Usuario '${MQTT_USER}' configurado"

# ------------------------------------------------------------
# PASO 4: Configurar Mosquitto con TLS
# ------------------------------------------------------------
print_step "PASO 4: Configurando Mosquitto con TLS"

# Respaldar configuración default si existe
if [ -f /etc/mosquitto/conf.d/default.conf ] && [ ! -f /etc/mosquitto/conf.d/default.conf.bak ]; then
    mv /etc/mosquitto/conf.d/default.conf /etc/mosquitto/conf.d/default.conf.bak
    print_info "Se respaldó default.conf"
fi

cat > "${CONF_FILE}" << EOF
# ============================================================
# Mosquitto MQTTS — Generado por setup_mqtts.sh
# ============================================================

# --- Listener MQTTS (TLS, puerto 8883) ---
listener 8883
certfile ${CERT_DIR}/server.crt
cafile ${CERT_DIR}/ca.crt
keyfile ${CERT_DIR}/server.key

# Requerir autenticación
allow_anonymous false
password_file ${PASSWD_FILE}

# --- Listener MQTT plano (solo localhost, para pruebas) ---
listener 1883 127.0.0.1
allow_anonymous false
password_file ${PASSWD_FILE}

# Logging
log_type error
log_type warning
log_type notice
log_type information
connection_messages true
log_timestamp true
EOF

print_ok "Configuración escrita en ${CONF_FILE}"

# ------------------------------------------------------------
# PASO 5: Firewall
# ------------------------------------------------------------
print_step "PASO 5: Configurando firewall"

if command -v ufw &> /dev/null; then
    ufw allow 8883/tcp
    print_ok "Puerto 8883 abierto en ufw"
else
    print_info "ufw no instalado. Si tienes firewall, abre el puerto 8883/tcp."
fi

# ------------------------------------------------------------
# PASO 6: Reiniciar Mosquitto
# ------------------------------------------------------------
print_step "PASO 6: Reiniciando Mosquitto"

systemctl enable mosquitto
systemctl restart mosquitto
sleep 2

if systemctl is-active --quiet mosquitto; then
    print_ok "Mosquitto ACTIVO — puerto 8883 (TLS) y 1883 (solo localhost)"
else
    echo -e "${RED}[ERROR] Mosquitto no arrancó. Logs:${NC}"
    journalctl -u mosquitto --no-pager -n 20
    exit 1
fi

# ------------------------------------------------------------
# RESUMEN FINAL
# ------------------------------------------------------------
echo -e "\n${GREEN}============================================================"
echo "  ✅ MQTTS CONFIGURADO CORRECTAMENTE"
echo "============================================================"
echo -e "${NC}"
echo -e "Broker:   ${BLUE}${BROKER_IP}:8883${NC} (TLS)"
echo -e "Usuario:  ${BLUE}${MQTT_USER}${NC}"
echo
echo -e "${YELLOW}─── SIGUIENTES PASOS ───${NC}"
echo
echo -e "1. Copia el certificado CA a tu Windows:"
echo -e "   ${BLUE}scp pi@${BROKER_IP}:/etc/mosquitto/certs/ca.crt ./ca.crt${NC}"
echo
echo -e "2. Copia el contenido de ca.crt al código del ESP32"
echo -e "   ${BLUE}sudo cat /etc/mosquitto/certs/ca.crt${NC}"
echo
echo -e "3. Prueba la conexión desde la Raspberry:"
echo -e "   ${BLUE}mosquitto_sub -h localhost -p 8883 -u ${MQTT_USER} -P '${MQTT_PASS}' -t test --cafile ${CERT_DIR}/ca.crt${NC}"
echo
