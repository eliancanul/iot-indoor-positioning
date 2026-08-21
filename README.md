# IoT Indoor Positioning

Plataforma para recolectar lecturas RSSI de ESP32 mediante MQTT y construir,
posteriormente, un radio-map para posicionamiento en interiores.

El proyecto mantiene dos caminos separados:

- **Estimación geométrica**: triángulos y círculos. Se conserva como baseline y
  diagnóstico.
- **Fingerprinting RSSI**: aprendizaje posterior de la relación entre el
  patrón RSSI y la posición real. Todavía no se entrena ni se conecta al flujo
  MQTT en vivo.

## Estado actual

La implementación actual permite:

- administrar áreas y anchors ESP32 desde la UI;
- calibrar `rssi_1m` y `n_pathloss` por nodo;
- conectarse a MQTT y suscribirse dinámicamente por área;
- conservar ciclos RSSI en tablas normalizadas;
- exigir una campaña y una sesión física explícitas para capturas nuevas;
- seleccionar explícitamente la posición objetivo del recorrido;
- clasificar muestras como `eligible` o `dirty` sin borrar datos crudos;
- auditar SQLite en modo de solo lectura;
- derivar CSV, manifiesto y reportes de cobertura reproducibles;
- seleccionar de forma determinista hasta 30 muestras por posición para el
  primer dataset de entrenamiento.

La base activa y los artefactos de auditoría reales no forman parte del
repositorio.

## Conceptos generales

### Área

Espacio físico rectangular donde se ubican los anchors y se desplaza el
beacon. El primer radio-map objetivo cubre un área de **4 × 2 metros**.

### Anchor

ESP32 fijo cuya lectura RSSI sirve como referencia para localizar el beacon.
La primera versión espera tres anchors.

### Ciclo de recolección

Ventana de lecturas RSSI de los tres anchors asociada a una única posición real.
Cada anchor aporta inicialmente 10 lecturas por ciclo.

### Posición real

Coordenada conocida del beacon durante un ciclo. Es la etiqueta contra la que
se evalúan las estimaciones; nunca debe convertirse en una feature de
inferencia.

### Posición objetivo del recorrido

Coordenada del orden fijo de una campaña que el operador selecciona antes de
capturar los próximos ciclos. Se copia como posición real de cada ciclo. No es
una estimación ni crea una sesión nueva.

### Campaña de captura

Esfuerzo físico planificado que agrupa sesiones y define las condiciones y el
orden fijo de posiciones. Para una cuadrícula de 1 metro en 4 × 2 metros, el
recorrido contiene 15 posiciones:

```text
(0,0), (1,0), (2,0), (3,0), (4,0)
(0,1), (1,1), (2,1), (3,1), (4,1)
(0,2), (1,2), (2,2), (3,2), (4,2)
```

### Sesión de captura

Unidad física de trabajo dentro de una campaña. Reiniciar Streamlit o MQTT no
crea automáticamente una sesión nueva. Una sesión nueva requiere orientación,
`environment_tag`, versión del layout, evidencia de independencia y una
descripción o referencia de obstáculos.

### Muestra cruda

Ciclo conservado con sus lecturas RSSI, timestamps, posición y metadatos,
independientemente de su utilidad para entrenamiento.

### Muestra elegible

Muestra cruda que cumple la política de calidad y puede contribuir al
radio-map.

### Muestra sucia

Muestra cruda conservada para auditoría, pero fuera del primer entrenamiento
por razones como RSSI inestable, anchor ausente, ventana temporal excesiva o
cantidad incorrecta de lecturas.

### Radio-map

Dataset de patrones RSSI etiquetados con posiciones reales para que un modelo
aprenda la relación entre señales y coordenadas.

## Arquitectura

```text
Streamlit (app.py)
    ├── admin_panel.py       Áreas y anchors
    ├── calibration.py       Calibración RSSI/path-loss
    ├── mqtt_manager.py      MQTT, ventanas RSSI y estimaciones geométricas
    └── database.py          SQLite, migraciones y persistencia normalizada

Auditoría offline
    ├── tools/audit_database.py
    └── tools/derive_dataset.py
```

La fuente canónica futura del fingerprinting es:

- `collection_sessions`;
- `fingerprint_samples`;
- `fingerprint_readings`.

La tabla legacy `dataset` se conserva por compatibilidad y se incluye solo en
la reconciliación de auditoría; no es la fuente del entrenamiento.

## Instalación local

Se requiere Python 3.11 o posterior. Crear un entorno virtual e instalar las
dependencias de la aplicación:

```bash
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate

pip install streamlit paho-mqtt matplotlib numpy
```

La base SQLite local se crea como `iot_platform.db` en el directorio del
proyecto. Ese archivo está excluido de Git.

## Ejecutar la aplicación

```bash
streamlit run app.py
```

La configuración MQTT se establece desde **Configuración**. No se deben
escribir credenciales reales en el código, firmware, scripts o documentación.

Los archivos de firmware contienen placeholders:

- `YOUR_WIFI_SSID`;
- `YOUR_WIFI_PASSWORD`;
- `YOUR_MQTT_USERNAME`;
- `YOUR_MQTT_PASSWORD`.

Sustituirlos únicamente en copias locales antes de flashear un ESP32. Los
scripts `setup_mqtts.sh` y `setup_mqtts_v2.sh` requieren `MQTT_PASS` desde el
entorno.

## Flujo de captura física

1. Detener MQTT y cerrar la aplicación antes de copiar o migrar la base.
2. En **Configuración → Contexto físico de captura**, crear una campaña con
   condiciones reales y recorrido fijo.
3. Abrir una sesión física con todos sus metadatos obligatorios.
4. Seleccionar la primera **posición objetivo del recorrido**.
5. Reanudar MQTT y esperar ciclos completos. Antes de cada posición siguiente,
   seleccionar su coordenada en la UI.
6. Cerrar la sesión al terminar. Las sesiones cerradas no aceptan ciclos nuevos.
7. Crear un backup externo de la base detenida.
8. Ejecutar la auditoría y la derivación sobre la copia, nunca sobre una base
   que esté siendo escrita.

No se deben contar reinicios técnicos como sesiones físicamente
independientes.

## Política inicial de calidad

La política se identifica como `rssi-policy-v1`:

- tres anchors esperados;
- 10 lecturas por anchor;
- ventana máxima entre lecturas de 20 segundos;
- `max_iqr_db = 10`;
- `max_std_db = 6`;
- RSSI fuera del rango permitido: sucio;
- anchor ausente: sucio y fuera del primer radio-map;
- triángulos y círculos: diagnósticos separados, no criterio de verdad.

El primer dataset de entrenamiento requiere exactamente 30 muestras elegibles
por posición y al menos tres sesiones físicamente independientes por posición.
Las muestras adicionales permanecen disponibles para validación temporal y
auditoría.

## Auditoría y derivación

Ejecutar sobre una copia detenida fuera del repositorio:

```bash
python tools/audit_database.py \
  --db C:/ruta/audits/iot_platform_YYYYMMDD_HHMMSS.db \
  --output C:/ruta/audits/audit.json

python tools/derive_dataset.py \
  --db C:/ruta/audits/iot_platform_YYYYMMDD_HHMMSS.db \
  --output-dir C:/ruta/audits/radiomap-v1
```

La auditoría verifica integridad, foreign keys, esquema, rangos básicos,
calidad y reconciliación legacy/normalizada sin modificar la entrada.

La derivación produce:

- `samples.csv`: todas las muestras clasificadas;
- `training.csv`: selección balanceada y determinista;
- `coverage.json`: cobertura por posición, sesión y campaña;
- `manifest.json`: política, features, etiquetas, conteos, IDs y hashes.

## Pruebas

```bash
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q .
git diff --check
```

## Seguridad y archivos locales

No versionar:

- la base SQLite activa;
- contraseñas, tokens o claves privadas;
- backups y reportes operativos con información del entorno;
- archivos comprimidos de firmware sin revisar;
- valores reales de Wi-Fi o MQTT.

El certificado `ca.crt` incluido es público. No contiene las claves privadas de
la CA o del broker; verificar su fingerprint por un canal confiable antes de
usarlo en una instalación.

Consultar [docs/agents/secret-hygiene.md](docs/agents/secret-hygiene.md) para
el procedimiento de credenciales locales.

## Decisiones de dominio

- [CONTEXT.md](CONTEXT.md): glosario del dominio.
- [ADR 0001: radio-map balanceado](docs/adr/0001-balanced-radiomap-dataset.md).
- [ADR 0002: contexto físico explícito](docs/adr/0002-explicit-capture-context.md).
- [Flujo seguro de auditoría y derivación](docs/agents/database-workflow.md).

El modelo de fingerprinting sigue bloqueado hasta completar las campañas,
verificar cobertura y fijar validaciones sin leakage.
