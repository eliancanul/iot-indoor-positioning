# Higiene de secretos y artefactos locales

Las credenciales de Wi-Fi y MQTT no forman parte del código versionado.

## Firmware

Los archivos `.ino` contienen placeholders `YOUR_WIFI_SSID`,
`YOUR_WIFI_PASSWORD`, `YOUR_MQTT_USERNAME` y `YOUR_MQTT_PASSWORD`. Antes de
flashear un ESP32, sustituirlos únicamente en una copia local fuera del commit.

## Scripts del broker

`setup_mqtts.sh` y `setup_mqtts_v2.sh` requieren `MQTT_PASS` en el entorno. No
escribir la contraseña en el script ni en la línea de comandos compartida.

## Artefactos excluidos

El reporte operativo de migración, el archivo comprimido de firmware y el
archivo temporal `nul` están excluidos mediante `.gitignore`. Las llaves
privadas del broker/CA tampoco deben entrar al repositorio.

`ca.crt` es el certificado público de la CA. No sustituye ni contiene las
llaves privadas del broker; si se distribuye, verificar siempre su fingerprint
por un canal confiable.

Si una credencial real estuvo previamente en una copia local, debe rotarse aun
cuando el archivo no se publique.
