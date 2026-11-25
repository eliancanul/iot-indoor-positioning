# Comparación offline

## Empezar sin hardware

```bash
pip install -r requirements.txt
streamlit run app.py --server.address 127.0.0.1
```

Después del acceso local, **Comparar** es la pantalla inicial. El acceso legacy
`admin/admin` es una puerta de prototipo, no autenticación segura: no expongas
esta aplicación públicamente ni la uses como control de acceso a datos privados.

1. Elige **Demo sintética**.
2. Reserva otra sesión/campaña o una posición no aprendida.
3. Pulsa **Comparar los tres métodos**.
4. Revisa media, mediana, P90 y cobertura en metros, mapa y muestras.
5. Descarga el JSON para repetir la comparación.

La demo es determinista (semilla 2026), enteramente sintética y sin mediciones
reales. Usa log-distance, por lo que favorece el baseline de círculos. No sirve
para escoger un ganador real ni comunicar precisión de hardware.

## Capturas reales

No cargues la base activa. Primero termina las campañas, cierra las sesiones,
detén la aplicación/MQTT y copia la base fuera del repositorio. Conserva un backup.

```bash
python tools/audit_database.py --db /ruta/copia-detenida.db --output /ruta/audit.json
python tools/derive_dataset.py --db /ruta/copia-detenida.db --output-dir /ruta/radiomap
```

Carga `training.csv` y `manifest.json` del mismo export en **Export de captura**.
Se procesan en el servidor donde corre Streamlit, no necesariamente en el
navegador. Usa tu instalación local para material privado. El programa no envía
los datos a un servicio de ML externo ni guarda modelos entrenados.

El importador exige:

- política `rssi-policy-v1`, integridad SQLite/foreign keys y hash del CSV;
- exactamente 450 muestras elegibles: 30 por cada una de las 15 posiciones;
- al menos tres sesiones con evidencia física por posición;
- sesiones cerradas, campaña, orientación, entorno, layout y obstáculos;
- una sola área de 4 × 2 m, layout y esquema de anchors;
- tres anchors completos, RSSI finito en [-150, 0], 10 lecturas, IQR ≤10,
  desviación ≤6 y ventana documentada ≤20 segundos;
- IDs/ciclos únicos y consistencia de metadatos entre CSV y manifiesto;
- calibración explícita por anchor y coincidencia de su orden con las features.

El gate comprueba condiciones documentadas, no puede acreditar independencia
física. Revisa esa evidencia y la calibración antes de confirmar en la UI.
La reconciliación legacy continúa en el manifiesto para auditoría; nunca es una
fuente de features o etiquetas y debe revisarse por separado. El export v1
antiguo carece del nuevo hash/contexto: vuelve a derivarlo, no edites sus hashes
para hacerlo pasar.

Si hay varias áreas o layouts, prepara una fuente detenida y auditada de una
sola área/layout; no se mezclan silenciosamente. El primer contrato admite solo
4 × 2 m. Las muestras extra continúan en `samples.csv` para futura validación
independiente; esta versión evalúa la selección inicial balanceada.

## Repetir desde CLI

```bash
python tools/compare_positioning.py --demo --output /ruta/demo-comparison.json
python tools/compare_positioning.py --demo --mode spatial --hold-position 2 1 --output /ruta/spatial-comparison.json
python tools/compare_positioning.py --training /ruta/radiomap/training.csv --manifest /ruta/radiomap/manifest.json --reviewed-context --output /ruta/comparison.json
```

La CLI no sobrescribe archivos existentes. El JSON incluye hashes, IDs de
train/test/no utilizados, versiones de Python/numpy/scikit-learn, features,
parámetros, predicciones y métricas. No exporta RSSI crudo, contraseñas, ruta de la
base ni notas del operador. Conserva el reporte fuera de Git si viene de datos
privados. Reproducibilidad numérica exacta requiere las mismas versiones.

## Cómo interpretar la comparación

- **WkNN**: normaliza RSSI con media/desviación de entrenamiento y promedia las
  coordenadas de k vecinos, ponderando por inverso de distancia. Coincidencias
  exactas promedian todas las muestras idénticas, sin división por cero.
- **Árbol de decisión**: CART binario, salida continua (x, y), profundidad máxima
  configurable y mínimo dos muestras por hoja. Usa las mismas features y el
  mismo entrenamiento. No es una clasificación de zonas.
- **Círculos**: algoritmo robusto existente, límites del área y calibración del
  snapshot al exportar. No se inventa una calibración histórica por ciclo.

La prueba reserva una campaña completa cuando hay varias, o una sesión completa
cuando solo hay una campaña. No divide al azar filas de la misma sesión entre
train y test. La prueba espacial además retira la posición elegida de todas las
sesiones de entrenamiento. Filas fuera de ese protocolo quedan identificadas
como no utilizadas. No hay validación cruzada ni una afirmación de generalización
estadística a partir de este holdout exploratorio.

Media/mediana/P90 usan distancia euclídea y exactamente la misma intersección de
muestras válidas para los tres métodos. Cobertura indica las predicciones
producidas sobre el total reservado. Si algún método no produce ninguna, la
comparación común queda sin métricas en vez de fabricar un cero.

Cambiar datos, manifiesto, parámetros o partición invalida resultados anteriores.
Repetir ajustes mirando el holdout lo convierte en validación exploratoria:
reserva una campaña nueva para la confirmación final. Esta versión no elige
hiperparámetros ni declara un ganador automáticamente.

El formulario manual pide solo RSSI y reutiliza el subconjunto de entrenamiento.
No pide coordenadas reales. Advierte señales fuera del rango de entrenamiento;
no puede detectar con certeza dispositivos fuera del área. La API rechaza
anchors ausentes, extraños y RSSI inválido en vez de rellenarlos silenciosamente.
