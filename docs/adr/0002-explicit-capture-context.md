---
status: accepted
---

# Contexto físico explícito para campañas y sesiones

Las capturas nuevas deben registrar su contexto físico mediante una campaña y una sesión explícitas. Reiniciar Streamlit o MQTT no crea una sesión física nueva.

## Decisión

La UI de settings permite crear una campaña con:

- código y descripción;
- condiciones ambientales;
- versión del protocolo;
- orden fijo de las posiciones.

Cada sesión nueva registra como mínimo:

- orientación (`north`, `east`, `south`, `west` o `unknown`);
- `environment_tag` controlado;
- versión del layout de anchors;
- evidencia de independencia física (horario, desmontaje/recolocación y condiciones ambientales);
- fotografía de obstáculos o descripción detallada.

La información vive en la estructura normalizada. Las sesiones históricas pueden tener esos campos nulos para no inventar información; el exportador no las considera sesiones físicamente independientes sin evidencia explícita.

## Consecuencias

- La cobertura del radio-map puede distinguir muestras de sesiones realmente independientes.
- Un reinicio técnico no contamina la definición de sesión física.
- Las capturas nuevas requieren una preparación adicional antes de iniciar MQTT.
- El esquema se amplía de forma aditiva y no elimina datos históricos.
- La orientación y el entorno son metadatos de auditoría/agrupación, no la posición real ni una sustitución de las features RSSI.
