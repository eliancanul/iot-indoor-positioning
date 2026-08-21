---
status: accepted
---

# Radio-map balanceado y datos crudos inmutables

La captura cruda se conservará sin borrado destructivo y el entrenamiento de fingerprinting usará un dataset derivado de muestras elegibles. El primer radio-map cubrirá las 15 posiciones de una cuadrícula de 1 metro en el área de 4 × 2 m, exigirá 30 muestras válidas por posición provenientes de al menos 3 sesiones de captura físicamente independientes y balanceará el primer entrenamiento a 30 muestras por posición; las muestras adicionales permanecerán disponibles para validación temporal y auditoría. Las sesiones se agruparán en campañas físicas: en el snapshot inicial, las fechas anteriores a hoy forman la campaña 1 y las muestras de hoy forman la campaña 2.

Se eligió esta política porque el snapshot actual concentra las muestras en pocas posiciones y mezcla ciclos de distinta calidad. Separar muestra cruda, muestra elegible y dataset de entrenamiento permite limpiar sin perder evidencia, evita que una posición domine el modelo y deja a las estimaciones geométricas como baselines/diagnósticos, no como verdad de entrenamiento.
