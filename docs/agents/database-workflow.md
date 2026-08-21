# Flujo seguro de auditoría y derivación

La base activa no se copia ni se migra mientras la captura MQTT esté ejecutándose.

## Auditoría de una copia detenida

1. Detener la captura y cerrar la aplicación.
2. Crear una copia con fecha fuera del repositorio.
3. Ejecutar el auditor en modo de solo lectura:

```bash
python tools/audit_database.py \
  --db C:/ruta/audits/iot_platform_YYYYMMDD_HHMMSS.db \
  --output C:/ruta/audits/audit.json
```

El auditor verifica integridad, foreign keys, esquema, calidad y reconciliación de `dataset` frente a las tablas normalizadas. No actualiza el archivo de entrada.

## Export derivado

Sobre la misma copia detenida:

```bash
python tools/derive_dataset.py \
  --db C:/ruta/audits/iot_platform_YYYYMMDD_HHMMSS.db \
  --output-dir C:/ruta/audits/radiomap-v1
```

El directorio contiene:

- `samples.csv`: todas las muestras clasificadas como `eligible` o `dirty`;
- `training.csv`: selección balanceada y determinista de 30 muestras por posición cubierta;
- `coverage.json`: cobertura por posición, sesión y campaña;
- `manifest.json`: política, features, etiquetas, hashes y conteos.

La tabla `dataset` legacy no se usa para el entrenamiento. Se conserva y aparece en la reconciliación del manifiesto.

## Captura física con posición explícita

En **Configuración → Contexto físico de captura**:

1. Crear la campaña con las condiciones reales y el recorrido fijo.
2. Abrir o reanudar una sesión física con todos sus metadatos obligatorios.
3. Seleccionar explícitamente la posición real que etiquetará los próximos ciclos.
4. Antes de cada posición, seleccionar la siguiente coordenada del recorrido. El cambio descarta solo la ventana RSSI pendiente; no borra muestras persistidas.

Mientras no haya sesión y posición explícitas, MQTT no guarda ciclos nuevos. Reiniciar Streamlit o MQTT no cambia la sesión ni selecciona una posición por sí mismo.

## Migración de esquema

El código contiene migraciones aditivas para campañas, metadatos de sesión y ventana temporal. No se debe ejecutar una migración sobre la base activa sin un respaldo separado y una comparación posterior de conteos de `areas`, `esp32`, `dataset`, `collection_sessions`, `fingerprint_samples` y `fingerprint_readings`.
