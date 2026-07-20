"""
admin_panel.py — Panel de administración para gestión de áreas y ESP32.
Se integra como una vista/tab dentro del sidebar o como página en el dashboard.
"""

import streamlit as st
import database as db


def render_admin_panel():
    """Renderiza el panel completo de administración."""

    st.markdown("## ⚙️ Panel de Administración")
    st.markdown("Gestiona áreas y nodos ESP32 del sistema.")
    st.markdown("---")

    # Tabs para separar Áreas y ESP32
    tab_areas, tab_esp32 = st.tabs(["🏢 Áreas", "📡 Nodos ESP32"])

    # ============================================================
    # TAB: ÁREAS
    # ============================================================
    with tab_areas:
        col_form, col_lista = st.columns([1, 1.5])

        # --- Formulario de área ---
        with col_form:
            st.markdown("### ➕ Nueva Área")

            with st.form("form_area", clear_on_submit=True):
                nombre = st.text_input("Nombre del área", placeholder="Ej: Laboratorio A")
                col_a, col_b = st.columns(2)
                with col_a:
                    ancho = st.number_input("Ancho (m)", min_value=0.5, value=8.0, step=0.5)
                with col_b:
                    alto = st.number_input("Alto (m)", min_value=0.5, value=6.0, step=0.5)

                st.markdown("**Punto real de referencia** (para calcular error)")
                col_px, col_py = st.columns(2)
                with col_px:
                    pr_x = st.number_input("X real (m)", min_value=0.0, value=2.0, step=0.5)
                with col_py:
                    pr_y = st.number_input("Y real (m)", min_value=0.0, value=2.0, step=0.5)

                submit = st.form_submit_button("Crear Área", use_container_width=True, type="primary")

                if submit:
                    if not nombre.strip():
                        st.error("El nombre es obligatorio.")
                    else:
                        ok, result = db.crear_area(nombre, ancho, alto, pr_x, pr_y)
                        if ok:
                            st.success(f"Área '{nombre}' creada (ID: {result})")
                            st.rerun()
                        else:
                            st.error(f"Error: {result}")

        # --- Lista de áreas existentes ---
        with col_lista:
            st.markdown("### 📋 Áreas Registradas")
            areas = db.listar_areas()

            if not areas:
                st.info("No hay áreas registradas. Crea la primera arriba.")
            else:
                for area in areas:
                    nodos = db.listar_esp32_por_area(area['id'])
                    with st.expander(
                        f"🏢 {area['nombre']} — {area['ancho']}×{area['alto']}m "
                        f"({len(nodos)}/3 ESP32)"
                    ):
                        col_info, col_acciones = st.columns([2, 1])

                        with col_info:
                            st.write(f"**ID:** {area['id']}")
                            st.write(f"**Dimensiones:** {area['ancho']} × {area['alto']} m")
                            st.write(f"**Punto real:** ({area['punto_real_x']}, {area['punto_real_y']})")
                            st.write(f"**Creada:** {area['creado_en']}")
                            if nodos:
                                st.write("**ESP32 asignados:**")
                                for n in nodos:
                                    st.write(
                                        f"  • {n['node_id']} → "
                                        f"topic `{n['topic']}` "
                                        f"pos=({n['pos_x']},{n['pos_y']}) "
                                        f"rssi_1m={n['rssi_1m']}"
                                    )
                            else:
                                st.write("**ESP32 asignados:** ninguno")

                        with col_acciones:
                            # --- Editar área ---
                            with st.popover("✏️ Editar", use_container_width=True):
                                st.markdown("**Editar área**")
                                new_name = st.text_input("Nombre", value=area['nombre'], key=f"en_{area['id']}")
                                col_ea, col_eb = st.columns(2)
                                with col_ea:
                                    new_ancho = st.number_input("Ancho", value=float(area['ancho']), key=f"ea_{area['id']}")
                                with col_eb:
                                    new_alto = st.number_input("Alto", value=float(area['alto']), key=f"eb_{area['id']}")
                                col_ex, col_ey = st.columns(2)
                                with col_ex:
                                    new_prx = st.number_input("X real", value=float(area['punto_real_x']), key=f"ex_{area['id']}")
                                with col_ey:
                                    new_pry = st.number_input("Y real", value=float(area['punto_real_y']), key=f"ey_{area['id']}")

                                if st.button("Guardar", key=f"save_a_{area['id']}", use_container_width=True):
                                    db.actualizar_area(
                                        area['id'], new_name, new_ancho, new_alto, new_prx, new_pry
                                    )
                                    st.success("Área actualizada.")
                                    st.rerun()

                            # --- Eliminar área ---
                            if st.button("🗑️ Eliminar", key=f"del_a_{area['id']}"):
                                ok, msg = db.eliminar_area(area['id'])
                                if ok:
                                    st.success("Área eliminada.")
                                    st.rerun()
                                else:
                                    st.error(msg)

    # ============================================================
    # TAB: ESP32
    # ============================================================
    with tab_esp32:
        col_form, col_lista = st.columns([1, 1.5])

        # --- Formulario ESP32 ---
        with col_form:
            st.markdown("### ➕ Nuevo ESP32")

            areas = db.listar_areas()
            if not areas:
                st.warning("Primero crea un área antes de registrar ESP32.")
            else:
                with st.form("form_esp32", clear_on_submit=True):
                    node_id = st.text_input("Node ID", placeholder="Ej: ESP32_003")
                    topic = st.text_input("Tópico MQTT", placeholder="Ej: RSSI_3")

                    col_x, col_y = st.columns(2)
                    with col_x:
                        pos_x = st.number_input("Posición X (m)", value=0.0, step=0.5)
                    with col_y:
                        pos_y = st.number_input("Posición Y (m)", value=0.0, step=0.5)

                    rssi_1m = st.number_input("RSSI a 1m (calibración)", value=-65.0, step=0.1)

                    area_options = {a['id']: a['nombre'] for a in areas}
                    area_sel = st.selectbox(
                        "Asignar al área",
                        options=list(area_options.keys()),
                        format_func=lambda x: area_options[x],
                    )

                    # Mostrar cupo del área seleccionada
                    nodos_area = db.listar_esp32_por_area(area_sel)
                    cupo = db.MAX_NODOS_POR_AREA - len(nodos_area)
                    if cupo <= 0:
                        st.error(f"El área '{area_options[area_sel]}' está llena (3/3).")
                    else:
                        st.info(f"Cupo disponible: {cupo}/{db.MAX_NODOS_POR_AREA}")

                    submit = st.form_submit_button("Registrar ESP32", use_container_width=True, type="primary")

                    if submit:
                        if not node_id.strip() or not topic.strip():
                            st.error("Node ID y Tópico son obligatorios.")
                        elif cupo <= 0:
                            st.error("El área seleccionada está llena.")
                        else:
                            ok, result = db.crear_esp32(
                                node_id, topic, pos_x, pos_y, rssi_1m, area_sel
                            )
                            if ok:
                                st.success(f"ESP32 '{node_id}' registrado (ID: {result})")
                                st.rerun()
                            else:
                                st.error(f"Error: {result}")

        # --- Lista de ESP32 ---
        with col_lista:
            st.markdown("### 📋 ESP32 Registrados")
            esp32s = db.listar_esp32()
            areas_map = {a['id']: a['nombre'] for a in db.listar_areas()}

            if not esp32s:
                st.info("No hay ESP32 registrados.")
            else:
                for esp in esp32s:
                    nombre_area = areas_map.get(esp['area_id'], '¿?')
                    with st.expander(
                        f"📡 {esp['node_id']} — {nombre_area} — topic: {esp['topic']}"
                    ):
                        col_info, col_acciones = st.columns([2, 1])

                        with col_info:
                            st.write(f"**ID:** {esp['id']}")
                            st.write(f"**Node ID:** {esp['node_id']}")
                            st.write(f"**Tópico:** `{esp['topic']}`")
                            st.write(f"**Posición:** ({esp['pos_x']}, {esp['pos_y']})")
                            st.write(f"**RSSI @1m:** {esp['rssi_1m']} dBm")
                            st.write(f"**Área:** {nombre_area} (ID {esp['area_id']})")

                        with col_acciones:
                            with st.popover("✏️ Editar", use_container_width=True):
                                st.markdown("**Editar ESP32**")
                                e_node = st.text_input("Node ID", value=esp['node_id'], key=f"en_{esp['id']}")
                                e_topic = st.text_input("Tópico", value=esp['topic'], key=f"et_{esp['id']}")
                                col_ex, col_ey = st.columns(2)
                                with col_ex:
                                    e_x = st.number_input("X", value=float(esp['pos_x']), key=f"ex_{esp['id']}")
                                with col_ey:
                                    e_y = st.number_input("Y", value=float(esp['pos_y']), key=f"ey_{esp['id']}")
                                e_rssi = st.number_input("RSSI @1m", value=float(esp['rssi_1m']), key=f"er_{esp['id']}")

                                area_opts = {a['id']: a['nombre'] for a in db.listar_areas()}
                                e_area = st.selectbox(
                                    "Área",
                                    options=list(area_opts.keys()),
                                    format_func=lambda x: area_opts[x],
                                    index=list(area_opts.keys()).index(esp['area_id']) if esp['area_id'] in area_opts else 0,
                                    key=f"ea_{esp['id']}",
                                )

                                if st.button("Guardar", key=f"save_e_{esp['id']}", use_container_width=True):
                                    try:
                                        db.actualizar_esp32(e_node, e_topic, e_x, e_y, e_rssi, e_area)
                                        st.success("ESP32 actualizado.")
                                        st.rerun()
                                    except Exception as ex:
                                        st.error(f"Error: {ex}")

                            if st.button("🗑️ Eliminar", key=f"del_e_{esp['id']}"):
                                db.eliminar_esp32(esp['id'])
                                st.success("ESP32 eliminado.")
                                st.rerun()
