"""Task-oriented, offline comparison screen for the existing Streamlit app."""
import json

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from positioning import DatasetError, FingerprintModel, METHODS, compare, load_export, make_demo, split_dataset


def render_comparison_panel():
    st.title("Compara cómo te localizas")
    st.caption("LABORATORIO OFFLINE  /  RSSI → posición en metros")
    st.write("Un mismo radio-map. Dos modelos de fingerprinting y el baseline de círculos, evaluados con las mismas capturas reservadas.")
    st.info("Empieza con la demo o carga un export auditado. Esta pantalla no conecta MQTT ni escribe en tu base.")

    with st.container(border=True):
        st.subheader("1. Elige los datos")
        source = st.radio("Fuente del radio-map", ["Demo sintética", "Export de captura"], horizontal=True, key="lab_source")
        dataset = None
        reviewed = True
        if source == "Demo sintética":
            dataset = make_demo()
            st.warning("Datos simulados, no precisión real. El generador usa el mismo modelo de propagación que círculos; esta demo favorece ese baseline.")
        else:
            st.caption("Captura → cierra las sesiones → copia la base detenida → audita y deriva → carga los dos archivos. Nunca subas la base activa.")
            left, right = st.columns(2)
            training = left.file_uploader("training.csv", type=["csv"], key="lab_csv")
            manifest = right.file_uploader("manifest.json", type=["json"], key="lab_manifest")
            if training is not None and manifest is not None:
                try:
                    dataset = load_export(training.getvalue(), manifest.getvalue())
                except DatasetError as exc:
                    st.error(str(exc))
            else:
                st.info("Carga CSV y manifiesto del mismo export para verificar integridad y cobertura.")
            reviewed = st.checkbox("Revisé las campañas, la independencia física y la calibración del export.", key="lab_reviewed_" + (dataset.provenance["manifest_sha256"] if dataset else "pending"))
            st.caption("El hash verifica integridad, no la verdad física. Los archivos se procesan en el servidor donde ejecutas Streamlit. Usa tu instalación local para capturas privadas.")
        if dataset is None:
            st.session_state.pop("lab_result", None)
            return
        columns = st.columns(3)
        columns[0].metric("Capturas disponibles", len(dataset.rows))
        columns[1].metric("Sesiones", len({r["session_id"] for r in dataset.rows}))
        columns[2].metric("Área", "4 × 2 m")

    with st.container(border=True):
        st.subheader("2. Reserva capturas para probar")
        evaluation = st.radio("Qué quieres comprobar", ["Otra sesión o campaña", "Una posición no aprendida"], horizontal=True, key="lab_evaluation")
        mode = "group" if evaluation == "Otra sesión o campaña" else "spatial"
        position = (2.0, 1.0)
        if mode == "spatial":
            position = st.selectbox("Posición que no verá el entrenamiento (m)",
                                    sorted({tuple(point) for point in dataset.y}), index=7, key="lab_position")
        with st.expander("Parámetros y método"):
            a, b = st.columns(2)
            k = a.slider("Vecinos WkNN", 1, 15, 5, key="lab_k")
            depth = b.slider("Profundidad máxima del árbol", 1, 10, 6, key="lab_depth")
            st.write("Fingerprinting es la representación RSSI y su relación con una posición. WkNN busca vecinos ponderados; el árbol binario divide esas mismas features con reglas RSSI. Círculos usa distancias y geometría.")
            st.caption("Semilla fija: 2026. Normalización ajustada solo con entrenamiento. Elegir parámetros tras ver el holdout lo convierte en exploratorio; usa una campaña nueva para confirmar.")
        try:
            train, test, split = split_dataset(dataset, mode, position)
        except DatasetError as exc:
            st.error(str(exc))
            return
        st.write(f"{len(train)} para entrenar · {len(test)} para probar · {len(split['unused_ids'])} reservadas sin usar")
        st.caption(split["limitation"])
        if mode == "spatial":
            st.caption("Se excluye la posición de todo el entrenamiento y se prueba solo en un grupo independiente. Las demás filas quedan sin usar.")
        if dataset.provenance["kind"] == "measured":
            st.caption("Círculos reutiliza la calibración registrada al exportar. No hay un snapshot de calibración por ciclo; confirma que corresponde a estas capturas.")
        signature = (json.dumps(dataset.provenance, sort_keys=True), mode, position, k, depth, reviewed)
        if st.session_state.get("lab_signature") != signature:
            st.session_state.pop("lab_result", None)
        if st.button("Comparar los tres métodos", type="primary", disabled=not reviewed, key="lab_compare"):
            try:
                with st.spinner("Evaluando las mismas capturas en los tres métodos…"):
                    st.session_state.lab_result = compare(dataset, mode, position, k, depth)
                    st.session_state.lab_signature = signature
            except DatasetError as exc:
                st.error(str(exc))
        if not reviewed:
            st.info("Confirma la revisión del contexto físico antes de entrenar.")

    result = st.session_state.get("lab_result")
    if result is None:
        st.caption("Cuando compares, verás error medio, mediana, P90 y el mapa de predicciones.")
        return
    st.subheader("3. Mira el error, no solo el punto")
    st.caption(result["metric_scope"] + " Menor es mejor. P90: el 90 % de los errores queda por debajo de ese valor.")
    for column, (method, values) in zip(st.columns(3), result["metrics"].items()):
        with column, st.container(border=True):
            st.write(METHODS[method])
            st.metric("Error medio", f"{values['mean_m']:.2f} m" if values["n"] else "Sin comparación")
            if values["n"]:
                st.caption(f"Mediana {values['median_m']:.2f} m · P90 {values['p90_m']:.2f} m")
            st.caption(f"Cobertura {values['available']}/{values['test_total']} · Comparables {values['n']}")
    tab_map, tab_data, tab_provenance = st.tabs(["Mapa de errores", "Muestras", "Reproducibilidad"])
    with tab_map:
        method = st.selectbox("Método en el mapa", list(METHODS), format_func=METHODS.get, key="lab_map_method")
        samples = [s for s in result["samples"] if s["method"] == method and s["x"] is not None]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        for sample in samples:
            ax.plot([sample["x_real"], sample["x"]], [sample["y_real"], sample["y"]], color="#94a3b8", alpha=.5, linewidth=.8)
        ax.scatter([s["x_real"] for s in samples], [s["y_real"] for s in samples], color="#0f766e", marker="s", s=45, label="Posición real", zorder=3)
        ax.scatter([s["x"] for s in samples], [s["y"] for s in samples], color="#b45309", marker="x", s=35, label="Predicción", zorder=4)
        ax.scatter([a["pos_x"] for a in dataset.anchors], [a["pos_y"] for a in dataset.anchors], color="#334155", marker="^", s=80, label="Anchor", zorder=5)
        ax.set(xlim=(-.2, 4.2), ylim=(-.2, 2.2), xlabel="X (m)", ylabel="Y (m)", title=METHODS[method])
        ax.set_aspect("equal")
        ax.grid(alpha=.2)
        ax.legend(loc="upper center", bbox_to_anchor=(.5, -.18), ncol=3, frameon=False)
        fig.tight_layout()
        st.pyplot(fig, use_container_width=True)
        plt.close(fig)
        st.caption("Cuadrado: posición real. Cruz: predicción. La línea muestra el error en metros. Las mismas muestras aparecen en la tabla accesible.")
    with tab_data:
        st.dataframe(pd.DataFrame(result["samples"]), hide_index=True, use_container_width=True)
    with tab_provenance:
        st.write(f"Tipo de datos: {'sintéticos' if dataset.provenance['kind'] == 'synthetic' else 'capturas importadas'}")
        st.write(f"Grupo reservado: {result['split']['test_group']} · Semilla: {result['split']['seed']}")
        st.caption("El reporte incluye hashes, versiones, parámetros, IDs de la partición y errores por muestra. No incluye credenciales ni lecturas RSSI crudas.")
        st.download_button("Descargar comparación JSON", json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False),
                           file_name="comparacion-offline.json", mime="application/json", key="lab_download")
    with st.expander("Probar un fingerprint manual"):
        st.caption("Usa solo RSSI; no pide posición real. Se entrena con el subconjunto de entrenamiento reservado arriba. Esto no activa inferencia MQTT.")
        method = st.selectbox("Modelo para la consulta", ["wknn", "tree"], format_func=METHODS.get, key="lab_query_method")
        readings = {}
        for column, anchor, value in zip(st.columns(3), dataset.anchors, dataset.X[train].mean(axis=0)):
            readings[anchor["node_id"]] = column.number_input(f"RSSI {anchor['node_id']} (dBm)", min_value=-150.0, max_value=0.0,
                                                             value=float(round(value, 1)), step=1.0, key=f"lab_rssi_{anchor['node_id']}")
        if st.button("Estimar esta lectura", key="lab_predict"):
            model = FingerprintModel(method, k, depth).fit(dataset.X[train], dataset.y[train], [a["node_id"] for a in dataset.anchors])
            response = model.locate(readings)
            x, y = response["position"]
            st.write(f"Posición estimada: ({x:.2f}, {y:.2f}) m")
            if response["warning"]:
                st.warning(response["warning"])
            st.caption("Sin posición real de referencia no se puede calcular el error ni garantizar que el dispositivo esté dentro del área.")
