// ============================================================
//  ESP32 — Sistema de Posicionamiento IoT UQROO
//  VERSIÓN MQTTS (TLS seguro, puerto 8883)
// ============================================================
//
//  CAMBIOS RESPECTO A LA VERSIÓN MQTT PLANO:
//   1. WiFiClient → WiFiClientSecure
//   2. Se añade el certificado CA del broker
//   3. Puerto 1883 → 8883
//   4. Se llama a setCACert() antes de conectar
//   5. Todo lo demás (BLE, escaneo, publish) queda igual
//
//  REQUISITO: el broker (Raspberry) ya debe tener TLS configurado
//  con setup_mqtts.sh. Copia el contenido de ca.crt abajo.
// ============================================================

// Librerias del proyecto
#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <PubSubClient.h>
#include <WiFiClientSecure.h>   // ← CAMBIO: era WiFiClient.h
#include <WiFi.h>

// ==================== CONFIGURACIÓN ====================
// Direcciones MAC de los beacons BLE a localizar (optimizado: const char*)
const char* knownBLEAddresses[] = {"60:77:71:8e:7e:05"};
int scanTime = 1; // Segundos de escaneo
BLEScan* pBLEScan;
int rssi = 1234;

// Credenciales WiFi
const char* ssid = "YOUR_WIFI_SSID";
const char* wifi_password = "YOUR_WIFI_PASSWORD";

// Configuración MQTT (SECURE)
const char* mqtt_server = "192.168.2.2";
const int   mqtt_port   = 8883;          // ← CAMBIO: era 1883
const char* esp32_topic = "RSSI_5";      // Cambiar según el ESP32
const char* mqtt_username = "YOUR_MQTT_USERNAME";
const char* mqtt_password = "YOUR_MQTT_PASSWORD";
const char* clientID = "ESP32_5";        // Cambiar según el ESP32

// Nombre del beacon a detectar (centralizado)
const char* BEACON_NAME = "BlueCharm";

// ============================================================
//  CERTIFICADO CA DEL BROKER
// ============================================================
//  Pegar aquí el contenido de ca.crt generado en la Raspberry.
//  Obtenerlo con:  sudo cat /etc/mosquitto/certs/ca.crt
//  Cada línea debe terminar con \n y la siguiente con \.
//  Mantener el orden exacto: BEGIN ... datos ... END.
// ============================================================
const char* ca_cert = \
"-----BEGIN CERTIFICATE-----\n" \
"MIIDXTCCAkWgAwIBAgIJAKZ9E7...\n" \
"AQUI_VAN_TODAS_LAS_LINEAS_DEL_CERTIFICADO\n" \
"...\n" \
"-----END CERTIFICATE-----\n";
// ⚠️  REEMPLAZAR TODO EL BLOQUE DE ARRIBA CON TU ca.crt REAL

// ==================== OBJETOS GLOBALES ====================
WiFiClientSecure wifiClient;   // ← CAMBIO: era WiFiClient
PubSubClient client(wifiClient);  // ← CAMBIO: constructor simplificado

// ==================== FUNCIONES ====================
void connect_MQTT() {
    Serial.print(F("Conectando a MQTT seguro ("));
    Serial.print(mqtt_server);
    Serial.print(F(":"));
    Serial.print(mqtt_port);
    Serial.println(F(")..."));

    if (client.connect(clientID, mqtt_username, mqtt_password)) {
        Serial.println(F("✓ Conectado al broker MQTTS!"));
    } else {
        Serial.print(F("✗ Error MQTT, estado="));
        Serial.println(client.state());
        // Estados comunes de error TLS:
        //  -4 = TLS connection failed (revisar ca_cert)
        //  -2 = broker no responde (revisar IP/puerto/firewall)
        //  -1 = desconectado
    }
}

// ==================== CALLBACK BLE (sin cambios) ====================
class MyAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
    void onResult(BLEAdvertisedDevice advertisedDevice) {
        String deviceMAC = advertisedDevice.getAddress().toString();
        if (deviceMAC == knownBLEAddresses[0]) {  // Detección por MAC
            Serial.print(F("detectado: "));
            Serial.println(advertisedDevice.getName().c_str());
            rssi = advertisedDevice.getRSSI();
            Serial.print(F("RSSI: "));
            Serial.println(rssi);

            if (!client.publish(esp32_topic, String(rssi).c_str())) {
                Serial.println(F("RSSI send fail (will retry in loop)"));
            } else {
                Serial.println(F("RSSI sent!"));
            }
        }
    }
};

// ==================== SETUP ====================
void setup() {
    Serial.begin(115200);
    Serial.println(F("============================================"));
    Serial.println(F("  ESP32 IoT UQROO — Modo MQTTS (seguro)"));
    Serial.println(F("============================================"));

    // --- Configurar TLS ANTES de conectar al broker ---
    Serial.println(F("Cargando certificado CA..."));
    wifiClient.setCACert(ca_cert);   // ← NUEVO: valida el certificado del broker

    // --- Conectar WiFi ---
    Serial.print(F("Conectando a WiFi "));
    Serial.println(ssid);
    WiFi.begin(ssid, wifi_password);
    while (WiFi.status() != WL_CONNECTED) {
        delay(500);
        Serial.print(F("."));
    }
    Serial.println(F("\nWiFi conectado"));
    Serial.print(F("IP: "));
    Serial.println(WiFi.localIP());

    // --- Configurar MQTT (servidor + puerto seguro) ---
    client.setServer(mqtt_server, mqtt_port);   // ← CAMBIO: ahora usa 8883

    // --- Conectar MQTT ---
    connect_MQTT();

    // --- Configurar BLE ---
    Serial.println(F("Iniciando escaneo BLE..."));
    BLEDevice::init("");
    pBLEScan = BLEDevice::getScan();
    pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
    pBLEScan->setActiveScan(true);
    pBLEScan->setInterval(100);
    pBLEScan->setWindow(99);
}

// ==================== LOOP ====================
void loop() {
    // 1. Mantener la conexión MQTT viva
    if (!client.connected()) {
        Serial.println(F("MQTT desconectado, reintentando..."));
        connect_MQTT();
    }
    client.loop();

    // 2. Escaneo BLE
    BLEScanResults* foundDevices = pBLEScan->start(scanTime, false);
    pBLEScan->clearResults();

    delay(500);  // Pausa para no saturar el sistema
}
