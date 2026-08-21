#!/bin/bash
# ============================================================
#  CONFIGURACIÓN MQTTS — Adaptado a Raspberry Pi de UQROO
# ============================================================
#  Configura Mosquitto con TLS (puerto 8883) preservando la
#  configuración existente (password file, usuario "user").
#
#  USO:  sudo bash setup_mqtts_v2.sh
# ============================================================

set -e

# -------------------- CONFIGURACIÓN --------------------
MQTT_USER="user"                     # Usuario MQTT existente
MQTT_PASS="${MQTT_PASS:?Set MQTT_PASS in the environment before running this script}"                 # Password MQTT existente
BROKER_IP="192.168.2.2"
COUNTRY="MX"
STATE="Quintana Roo"
CITY="Chetumal"
ORG="UQROO"
CERT_DAYS="3650"
# -------------------------------------------------------

CERT_DIR="/etc/mosquitto/certs"
PASSWD_FILE="/etc/mosquitto/pwfile"   # ← Tu config real usa pwfile
CONF_FILE="/etc/mosquitto/mosquitto.conf"

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
echo "  Raspberry: raspberrypiserver (192.168.2.2)"
echo "============================================================"
echo -e "${NC}"

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR] Ejecutar como root: sudo bash setup_mqtts_v2.sh${NC}"
    exit 1
fi

# ------------------------------------------------------------
# PASO 1: Crear directorio de certificados
# ------------------------------------------------------------
print_step "PASO 1: Preparando directorios"
mkdir -p "${CERT_DIR}"
print_ok "Directorio listo: ${CERT_DIR}"

# ------------------------------------------------------------
# PASO 2: Generar certificados autofirmados
# ------------------------------------------------------------
print_step "PASO 2: Generando certificados (Broker IP: ${BROKER_IP})"

cd "${CERT_DIR}"

# Respaldar si ya existen
if [ -f "ca.key" ] || [ -f "ca.crt" ]; then
    BACKUP_DIR="${CERT_DIR}/backup_$(date +%Y%m%d_%H%M%S)"
    print_warn "Ya existen certificados. Respaldando en ${BACKUP_DIR}"
    mkdir -p "${BACKUP_DIR}"
    cp ca.key ca.crt server.key server.crt server.csr "${BACKUP_DIR}/" 2>/dev/null || true
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

# Firmar con la CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
    -CAcreateserial -out server.crt -days "${CERT_DAYS}" 2>/dev/null

# Permisos
chmod 600 *.key
chmod 644 *.crt
cd - > /dev/null

print_ok "Certificados generados en ${CERT_DIR}"
echo -e "  ${YELLOW}Copia ca.crt al ESP32 y al Windows${NC}"

# ------------------------------------------------------------
# PASO 3: Mantener el usuario MQTT existente
# ------------------------------------------------------------
print_step "PASO 3: Verificando usuario MQTT '${MQTT_USER}'"

if [ -f "${PASSWD_FILE}" ]; then
    print_ok "Archivo de passwords ya existe: ${PASSWD_FILE}"
    print_info "Usuario '${MQTT_USER}' preservado (no se modifica)"
else
    print_warn "Creando archivo de passwords nuevo..."
    mosquitto_passwd -b -c "${PASSWD_FILE}" "${MQTT_USER}" "${MQTT_PASS}"
    print_ok "Usuario '${MQTT_USER}' creado"
fi

# ------------------------------------------------------------
# PASO 4: Respaldo de mosquitto.conf y nueva config con TLS
# ------------------------------------------------------------
print_step "PASO 4: Configurando Mosquitto con TLS"

# Respaldo de la config actual
if [ ! -f "${CONF_FILE}.bak" ]; then
    cp "${CONF_FILE}" "${CONF_FILE}.bak"
    print_ok "Respaldo creado: ${CONF_FILE}.bak"
else
    print_info "Respaldo anterior ya existe: ${CONF_FILE}.bak"
fi

cat > "${CONF_FILE}" << EOF
# ============================================================
# Mosquitto MQTT + MQTTS — Configurado por setup_mqtts_v2.sh
# Fecha: $(date)
# ============================================================

pid_file /run/mosquitto/mosquitto.pid

persistence true
persistence_location /var/lib/mosquitto/

log_dest file /var/log/mosquitto/mosquitto.log
log_type error
log_type warning
log_type notice
log_type information
connection_messages true
log_timestamp true

# Requerir autenticación en todos los listeners
allow_anonymous false
password_file ${PASSWD_FILE}

# --- Listener MQTT plano (puerto 1883) ---
listener 1883

# --- Listener MQTTS (TLS, puerto 8883) ---
listener 8883
certfile ${CERT_DIR}/server.crt
cafile ${CERT_DIR}/ca.crt
keyfile ${CERT_DIR}/server.key

EOF

print_ok "Configuración escrita en ${CONF_FILE}"

# ------------------------------------------------------------
# PASO 5: Firewall
# ------------------------------------------------------------
print_step "PASO 5: Firewall"

if command -v ufw &> /dev/null; then
    ufw allow 8883/tcp
    print_ok "Puerto 8883 abierto en ufw"
else
    print_info "ufw no instalado. Abre el puerto 8883/tcp si tienes firewall manual."
fi

# ------------------------------------------------------------
# PASO 6: Reiniciar Mosquitto
# ------------------------------------------------------------
print_step "PASO 6: Reiniciando Mosquitto"

systemctl enable mosquitto
systemctl restart mosquitto
sleep 2

if systemctl is-active --quiet mosquitto; then
    print_ok "Mosquitto ACTIVO"
    echo -e "  ${GREEN}Puerto 1883 (MQTT plano) — funcional${NC}"
    echo -e "  ${GREEN}Puerto 8883 (MQTTS seguro) — funcional${NC}"
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
echo -e "Broker:    ${BLUE}${BROKER_IP}${NC}"
echo -e "  Puerto 1883 (MQTT plano)  — sigue funcionando"
echo -e "  Puerto 8883 (MQTTS TLS)   — nuevo"
echo -e "Usuario:   ${BLUE}${MQTT_USER}${NC}"
echo
echo -e "${YELLOW}─── CERTIFICADO CA (copiar al ESP32 y Windows) ───${NC}"
echo -e "Ubicación: ${BLUE}${CERT_DIR}/ca.crt${NC}"
echo
echo -e "${YELLOW}─── PRUEBA RÁPIDA ───${NC}"
echo -e "Desde la Raspberry:"
echo -e "  ${BLUE}mosquitto_sub -h localhost -p 8883 -u user -P password -t test --cafile ${CERT_DIR}/ca.crt${NC}"
echo
