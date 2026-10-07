---
status: accepted
---

# Laboratorio offline con gate de datos reales intacto

## Contexto y decisión reabierta

El gate previo bloqueaba incluso la implementación y prueba de modelos. El
encargo actual pide fingerprinting y árboles de decisión para comparar, además
de una UI más útil. Reabrimos únicamente esa restricción de implementación:
permitimos modelos efímeros offline y una demo sintética explícita. No afirmamos
que la captura física histórica haya superado el gate.

## Decisión

- WkNN y un árbol CART de regresión binario usan las mismas tres medianas RSSI.
  Fingerprinting es la representación/estrategia; ambos son modelos sobre ella.
- Reutilizar círculos sin modificar su algoritmo como baseline geométrico.
- La UI empieza en Comparar, sin conectar MQTT. No hay entrenamiento automático,
  registro de modelos, escritura a SQLite ni inferencia de estos modelos en MQTT.
- El importador exige el export normalizado con hash, 15 posiciones × 30 muestras,
  al menos tres sesiones por posición, contexto físico y sesiones cerradas.
  Verifica calidad de cada fila y rechaza mezcla de áreas, layouts o esquemas.
- La evidencia física sigue requiriendo revisión del operador. Hashes, textos o
  casillas no prueban independencia física ni autenticidad de una campaña.
- Holdout reproducible por campaña si hay varias, por sesión si solo hay una.
  El holdout espacial adicional elimina una posición de todo entrenamiento y
  solo evalúa esa posición en el grupo reservado. Todos los modelos comparten
  exactamente la partición. No hacemos tuning automático sobre el test.
- El escalador se ajusta solo con el entrenamiento. No entran como features
  coordenadas, IDs, orientación, errores ni timestamps.
- Las métricas de comparación usan la intersección de predicciones válidas y
  muestran denominador y cobertura por método. La unidad es el metro.

## Límites

La demo log-distance favorece círculos por construcción: prueba el recorrido de
la aplicación, no mide rendimiento de un sistema real. Un holdout entre sesiones
de una campaña no prueba generalización entre campañas. El árbol y WkNN no
certifican que una lectura provenga del interior del área; RSSI fuera del rango de
entrenamiento produce advertencia. Anchors ausentes o desconocidos se rechazan.

Las capturas actuales no guardan calibración por ciclo. Círculos se recalcula con
la calibración explícita por anchor disponible en la copia al exportar, y la UI
lo advierte. El operador debe confirmar su correspondencia con las capturas.
Los históricos sin contexto o calibración no se habilitan por esta decisión.

No se sustituyen ADR 0001/0002 ni se declara cumplido el gate operativo.
