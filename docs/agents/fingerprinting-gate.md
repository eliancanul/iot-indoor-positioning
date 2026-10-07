# Estado previo a integrar fingerprinting RSSI

Esta nota marca el estado del proyecto antes de implementar o conectar un
modelo de fingerprinting RSSI. Es un gate operativo: mientras los criterios
no estén cumplidos, no se debe entrenar un modelo ni añadir inferencia de
fingerprinting al flujo MQTT en vivo.

## Alcance revisado para el laboratorio offline

[ADR 0003](../adr/0003-offline-fingerprinting-comparison.md) reabre la
implementación de WkNN y árbol de decisión en un laboratorio aislado: permite
pruebas sintéticas y entrenamiento efímero sobre exports que pasan el gate y
han sido revisados por el operador. Esto no declara listas las capturas
históricas, no registra modelos ni activa inferencia de fingerprinting en MQTT.
Las restricciones de abajo se conservan para datos reales que no pasan el gate
y para el flujo de producción en vivo. La demo se identifica siempre como tal.

## Estado actual

La plataforma ya tiene implementados:

- captura MQTT dinámica por área;
- calibración de `rssi_1m` y `n_pathloss`;
- estimaciones geométricas de triángulos y círculos como baselines;
- persistencia normalizada de ciclos y lecturas RSSI;
- campañas y sesiones físicas con contexto explícito;
- selección explícita de la posición objetivo del recorrido;
- clasificación reproducible de muestras `eligible` y `dirty`;
- auditoría SQLite de solo lectura;
- derivación CSV, manifiesto y cobertura por posición, sesión y campaña.

La captura física nueva permanece protegida: requiere una sesión abierta y una
posición objetivo seleccionada. Reiniciar la aplicación o MQTT no crea una
sesión físicamente independiente.

El snapshot auditado antes de las campañas físicas nuevas registró:

- 549 muestras normalizadas;
- 1.647 lecturas de anchors;
- 447 muestras elegibles bajo `rssi-policy-v1`;
- 102 muestras sucias conservadas para auditoría;
- 0 muestras de entrenamiento seleccionadas;
- 0 campañas físicas explícitas para las sesiones históricas;
- reconciliación legacy/normalizada todavía abierta por ambigüedad.

Estos datos históricos no constituyen todavía un radio-map válido para
fingerprinting.

## Gate de entrada

Antes de crear un modelo se debe demostrar, mediante una copia detenida y un
export firmado por hashes, que:

1. las 15 posiciones de la cuadrícula de 4 × 2 m están representadas;
2. cada posición tiene al menos 30 muestras elegibles;
3. cada posición cubre al menos tres sesiones físicamente independientes;
4. cada sesión tiene campaña, orientación, entorno, layout, evidencia de
   independencia y obstáculos documentados;
5. las muestras sucias permanecen identificables y fuera del entrenamiento;
6. la selección de 30 muestras por posición es determinista y balanceada entre
   sesiones;
7. las muestras adicionales quedan disponibles para validación temporal y
   auditoría;
8. la partición posterior evita leakage por sesión/campaña y contiene un
   holdout espacial explícito;
9. las features de inferencia contienen únicamente señales RSSI y metadatos de
   calidad permitidos, nunca `x_real`, `y_real`, errores geométricos o
   información futura.

## Fuera de alcance hasta cerrar el gate

No se debe:

- entrenar o registrar k-NN, Random Forest u otro modelo;
- activar fingerprinting en la UI o en MQTT en vivo;
- usar triángulos o círculos como verdad de posición;
- convertir la tabla legacy `dataset` en fuente de entrenamiento;
- borrar o limpiar destructivamente muestras crudas;
- considerar un reinicio técnico como una sesión independiente.

## Secuencia siguiente

1. Ejecutar las campañas físicas faltantes con el recorrido fijo.
2. Cerrar cada sesión y respaldar la base fuera del repositorio.
3. Auditar y derivar `samples.csv`, `training.csv`, `coverage.json` y
   `manifest.json`.
4. Revisar cobertura, calidad, independencia y hashes con el operador.
5. Fijar particiones espacial y temporal sin leakage.
6. Solo después abrir el trabajo de baselines offline y evaluación de modelos.

La activación de fingerprinting en vivo queda pendiente hasta marcar este gate
como cumplido con evidencia verificable. Implementar y probar el laboratorio
offline no equivale a esa aprobación.
