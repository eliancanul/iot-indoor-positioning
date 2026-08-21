# Posicionamiento IoT en interiores

Este contexto describe la recolección de señales RSSI y la construcción de un radio-map para estimar posiciones dentro de un área conocida.

## Recolección

**Área**:
Espacio físico rectangular en el que se ubican anchors y posiciones conocidas del dispositivo que se está localizando.
_Avoid_: zona, escenario

**Anchor**:
ESP32 fijo cuya lectura RSSI sirve como referencia para localizar el dispositivo.
_Avoid_: sensor móvil, posición estimada

**Ciclo de recolección**:
Una ventana de lecturas RSSI de todos los anchors asociada a una única posición real del dispositivo.
_Avoid_: paquete, lectura individual

**Sesión de captura**:
Unidad de trabajo dentro de una campaña física, con ciclos recolectados en un periodo y condiciones concretos. Reiniciar la aplicación no define por sí mismo una sesión nueva.
_Avoid_: conexión MQTT, reinicio

**Campaña de captura**:
Esfuerzo físico planificado que agrupa una o más sesiones y distingue una ronda de recolección de otra, aunque ocurran en el mismo espacio. En la primera versión se registra desde settings con un código, descripción, condiciones ambientales y orden fijo de posiciones.
_Avoid_: día de base de datos, sesión MQTT

**Orientación de captura**:
Dirección física en la que está girado el dispositivo que se localiza respecto al marco del área durante una sesión: north, east, south, west o unknown. Es metadato de auditoría/agrupación, no la posición estimada ni una etiqueta adicional.
_Avoid_: rumbo estimado, posición calculada

**Etiqueta de entorno**:
Identificador controlado de las condiciones físicas de una sesión, por ejemplo `baseline-v1`; describe el contexto de radio y obstáculos sin sustituir la posición real.
_Avoid_: calidad RSSI, campaña

**Evidencia de independencia física**:
Descripción verificable de por qué una sesión representa una condición física independiente, incluyendo horario, desmontaje/recolocación y condiciones ambientales de la campaña.
_Avoid_: reinicio de aplicación, conexión MQTT

**Posición real**:
Coordenada conocida del dispositivo durante un ciclo de recolección; es la etiqueta contra la que se evalúan las estimaciones.
_Avoid_: posición calculada, predicción

**Posición objetivo del recorrido**:
Coordenada del orden fijo de una campaña que el operador selecciona antes de capturar los próximos ciclos. Se copia como posición real de cada ciclo; cambiarla no crea una sesión nueva ni es una estimación.
_Avoid_: posición estimada, reinicio técnico

## Dataset y calidad

**Muestra cruda**:
Ciclo de recolección conservado con sus lecturas y metadatos originales, independientemente de su calidad para entrenamiento.
_Avoid_: dato descartado

**Muestra elegible**:
Muestra cruda completa que cumple los criterios de calidad RSSI y puede considerarse para el radio-map de entrenamiento.
_Avoid_: muestra limpia definitiva

**Muestra sucia**:
Muestra cruda que se conserva para auditoría, pero queda fuera del entrenamiento inicial por calidad, cobertura o consistencia.
_Avoid_: basura, dato inútil

**Radio-map**:
Conjunto de patrones RSSI etiquetados con posiciones reales, organizado para que un modelo aprenda la relación entre señales y coordenadas.
_Avoid_: tabla de posiciones, mapa geométrico

**Dataset de entrenamiento**:
Selección derivada y reproducible de muestras elegibles, balanceada por posición y separada de las muestras crudas históricas.
_Avoid_: base original, dataset legacy

## Estimación

**Estimación geométrica**:
Posición calculada mediante distancias derivadas del RSSI y la geometría de los anchors, incluyendo los métodos de triángulos y círculos.
_Avoid_: verdad de posición

**Fingerprinting RSSI**:
Estimación que aprende directamente la relación entre el patrón RSSI de los anchors y la posición real del dispositivo.
_Avoid_: trilateración, triangulación
