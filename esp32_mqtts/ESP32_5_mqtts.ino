// ============================================================
//  ESP32 — Sistema de Posicionamiento IoT UQROO
//  VERSIÓN MQTTS (TLS seguro, puerto 8883)
//  Nodo: ESP32_5 | Topic: RSSI_5
// ============================================================

#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <PubSubClient.h>
#include <WiFiClientSecure.h>
#include <WiFi.h>

// ==================== CONFIGURACIÓN ====================
const char* knownBLEAddresses[] = {"60:77:71:8e:7e:05"};
int scanTime = 1;
BLEScan* pBLEScan;
int rssi = 1234;

const char* ssid = "YOUR_WIFI_SSID";
const char* wifi_password = "YOUR_WIFI_PASSWORD";

const char* mqtt_server = "192.168.2.2";
const int   mqtt_port   = 8883;
const char* esp32_topic = "RSSI_5";
const char* mqtt_username = "YOUR_MQTT_USERNAME";
const char* mqtt_password = "YOUR_MQTT_PASSWORD";
const char* clientID = "ESP32_5";

// ==================== CERTIFICADO CA ====================
const char* ca_cert = \
    "-----BEGIN CERTIFICATE-----\n" \
    "MIIDnTCCAoWgAwIBAgIUC7WGBDInKcfAmtVWeMXSnkc7ZqcwDQYJKoZIhvcNAQEL\n" \
    "BQAwXjELMAkGA1UEBhMCTVgxFTATBgNVBAgMDFF1aW50YW5hIFJvbzERMA8GA1UE\n" \
    "BwwIQ2hldHVtYWwxDjAMBgNVBAoMBVVRUk9PMRUwEwYDVQQDDAxJb1QtVVFST08t\n" \
    "Q0EwHhcNMjYwNjEwMDgxNjUwWhcNMzYwNjA3MDgxNjUwWjBeMQswCQYDVQQGEwJN\n" \
    "WDEVMBMGA1UECAwMUXVpbnRhbmEgUm9vMREwDwYDVQQHDAhDaGV0dW1hbDEOMAwG\n" \
    "A1UECgwFVVFST08xFTATBgNVBAMMDElvVC1VUVJPTy1DQTCCASIwDQYJKoZIhvcN\n" \
    "AQEBBQADggEPADCCAQoCggEBAN9TEqK9ECLO8IKKaqgL4Xi7it4Ohm4VjmJ3lWGY\n" \
    "vdyCTZwbEjdEImMm91tVeQ+FfdNJgk2PvrhgKHP32SkZhYgLby3cytZzMbgFH436\n" \
    "T5Ewv98nE7bTAc6tG13SUCyI1HqOa5+f8q6Ny846nlYFn+s3LMTJ/Jg8cnvIdDU0\n" \
    "DBE3zaYo3RCjh+xPTs9r8J5rPWhN1vtwChnW1h71uQKzA3ceagaM0TQNIYuWJ0rn\n" \
    "aV9z3zdCjnIHHywhwfCSQgv8IWkKwMvE40atm2A1R4NY+sFXLoioNO3ddwPS41Jc\n" \
    "76voD69aQ8fA3J7AjwrQIepeDKSrv23ggqV/c3dI3BJyxPUCAwEAAaNTMFEwHQYD\n" \
    "VR0OBBYEFF+liIrbASGaZW1O6KwKUNlbqKivMB8GA1UdIwQYMBaAFF+liIrbASGa\n" \
    "ZW1O6KwKUNlbqKivMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEB\n" \
    "AMDuf/ENChpnHLKwBCWkDlvPDtRNGdiasIzgwX5MM966bIJdsvFn9DofoEPli/a9\n" \
    "agWoez61W9O4tzjWOiwcBxbBNrd94Y8WveMm46nJ30ilzIJX/ZJ3KaiaZYsRKq1j\n" \
    "bGkpjjPnpLsFDCCJ42kKt058yaIReAHuuMv58yKTsZ1tZMHuzgbrI0AiHerb6zEF\n" \
    "5GMVJkSIP2KrubnA5lE3OD/IW28PFXTT1gAQA6alhK4CzjqpSFrry7iAZOzuHaCZ\n" \
    "4vCkQqB6c3S5fZ4PUgR1qDGVb4N443dIdES0oaTWCJ22xqDhSAO2lSRgNh1OqTlk\n" \
    "UCpEe2E+my6w2URvt8UoLvA=\n" \
    "-----END CERTIFICATE-----\n" ;

// ==================== OBJETOS ====================
WiFiClientSecure wifiClient;
PubSubClient client(wifiClient);

// ==================== FUNCIONES ====================
void connect_MQTT() {
    Serial.print(F("Conectando a MQTT seguro ("));
    Serial.print(mqtt_server);
    Serial.print(F(":"));
    Serial.print(mqtt_port);
    Serial.println(F(")..."));
    if (client.connect(clientID, mqtt_username, mqtt_password)) {
        Serial.println(F("Conectado al broker MQTTS!"));
    } else {
        Serial.print(F("Error MQTT, estado="));
        Serial.println(client.state());
    }
}

// ==================== CALLBACK BLE ====================
class MyAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
    void onResult(BLEAdvertisedDevice advertisedDevice) {
        String deviceMAC = advertisedDevice.getAddress().toString();
        if (deviceMAC == knownBLEAddresses[0]) {
            Serial.print(F("detectado: "));
            Serial.println(advertisedDevice.getName().c_str());
            rssi = advertisedDevice.getRSSI();
            Serial.print(F("RSSI: "));
            Serial.println(rssi);
            if (!client.publish(esp32_topic, String(rssi).c_str())) {
                Serial.println(F("RSSI send fail"));
            } else {
                Serial.println(F("RSSI sent!"));
            }
        }
    }
};

// ==================== SETUP ====================
void setup() {
    Serial.begin(115200);
    Serial.println(F("===================================="));
    Serial.println(F("  ESP32_5 — Modo MQTTS (seguro)"));
    Serial.println(F("===================================="));

    wifiClient.setCACert(ca_cert);

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

    client.setServer(mqtt_server, mqtt_port);
    connect_MQTT();

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
    if (!client.connected()) {
        Serial.println(F("MQTT desconectado, reintentando..."));
        connect_MQTT();
    }
    client.loop();

    BLEScanResults* foundDevices = pBLEScan->start(scanTime, false);
    pBLEScan->clearResults();
    delay(500);
}
