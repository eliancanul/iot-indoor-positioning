import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import math
import io
import time
import csv

# ============ MÓDULOS PROPIOS ============
import database as db
import mqtt_manager
import admin_panel
import calibration
from comparison_panel import render_comparison_panel


def _monitor_reference_position(manager, area_id, area):
    """Usa la posición de captura explícita cuando existe; conserva el fallback legacy."""
    capture_position = manager.obtener_posicion_captura(area_id)
    if capture_position is not None:
        return capture_position
    return area["punto_real_x"], area["punto_real_y"]


# ============ INICIALIZACIÓN DE BD ============
db.init_db()
db.cargar_datos_semilla()

# ============ CONFIGURACIÓN DE PÁGINA ============
st.set_page_config(page_title="Plataforma IoT | UQROO", page_icon="📡", layout="wide")

# ============ CSS ============
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container { padding-top: 2.5rem; padding-bottom: 3rem; max-width: 1250px; }
    button:focus-visible, input:focus-visible { outline: 3px solid #0f766e !important; outline-offset: 3px; }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; transform: none !important; } }
    @media (max-width: 600px) { .block-container { padding: 1.25rem 1rem; } }
    .stButton>button {
        border-radius: 8px; font-weight: 600; transition: all 0.3s ease;
    }
    .stButton>button:hover {
        transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    div[data-testid="stMetricValue"] { font-size: 2rem; color: #1F618D; }
</style>
""", unsafe_allow_html=True)


# ============ LOGIN ============
if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    st.markdown("<div style='margin-top: 10vh;'></div>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <h1 style='color: #1F618D; margin-bottom: 0px; font-size: 2.8rem;'>📡 Plataforma IoT</h1>
                <p style='color: #7F8C8D; font-size: 1.2rem; margin-top: 5px;'>Sistema de Posicionamiento en Interiores</p>
                <hr style='border: 1px solid #EAECEE; margin-bottom: 25px;'>
            </div>
        """, unsafe_allow_html=True)
        usuario = st.text_input("👤 Usuario", placeholder="Ingresa tu usuario")
        password = st.text_input("🔑 Contraseña", type="password", placeholder="••••••••")
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Ingresar al Sistema", use_container_width=True, type="primary"):
            if usuario == "admin" and password == "admin":
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas. Verifique e intente nuevamente.")
        st.markdown("""
            <div style='text-align: center; margin-top: 40px;'>
                <small style='color: #BDC3C7;'>Estancia Profesional 2026 • UPA - UQROO</small>
            </div>
        """, unsafe_allow_html=True)

# ============================================================
# DASHBOARD PRINCIPAL
# ============================================================
else:

    # ============ NAVEGACIÓN PRINCIPAL ============
    st.sidebar.markdown("<h2 style='color: #1F618D;'>📡 Plataforma IoT</h2>", unsafe_allow_html=True)
    pagina = st.sidebar.radio(
        "Navegación:",
        ["📍 Comparar", "🖥️ Monitoreo", "🔬 Calibración", "⚙️ Administración", "🔧 Configuración"]
    )

    st.sidebar.caption("Captura con contexto físico. Compara con datos reservados.")
    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

    # ============================================================
    # PÁGINA: ADMINISTRACIÓN (FASE 3)
    # ============================================================
    if pagina == "📍 Comparar":
        render_comparison_panel()

    elif pagina == "⚙️ Administración":
        admin_panel.render_admin_panel()

    # ============================================================
    # PÁGINA: CALIBRACIÓN
    # ============================================================
    elif pagina == "🔬 Calibración":
        calibration.render_calibration_panel()

    # ============================================================
    # PÁGINA: CONFIGURACIÓN (FASE 5)
    # ============================================================
    elif pagina == "🔧 Configuración":
        st.markdown("## 🔧 Configuración del Sistema")
        st.markdown("---")

        config = db.get_all_config()

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### 📡 Parámetros MQTT")
            mqtt_broker = st.text_input("Broker", value=config.get('mqtt_broker', ''))
            mqtt_port = st.number_input("Puerto", value=int(config.get('mqtt_port', 1883)))
            mqtt_user = st.text_input("Usuario", value=config.get('mqtt_user', ''))
            mqtt_pass = st.text_input("Contraseña", type="password", value=config.get('mqtt_password', ''))

            st.markdown("### 📊 Parámetros de Estimación")
            n_pathloss = st.number_input(
                "Factor de pérdida (n_pathloss)",
                value=float(config.get('n_pathloss', 3.223)),
                step=0.01, format="%.3f"
            )
            n_muestras = st.number_input(
                "Muestras por ciclo",
                min_value=1, max_value=100,
                value=int(config.get('n_muestras', 10))
            )
            max_iqr_db = st.number_input(
                "IQR máximo de RSSI (dB)",
                min_value=0.0, max_value=50.0,
                value=float(config.get('max_iqr_db', 10.0)),
                step=0.5, format="%.1f",
                help="Variación intercuartílica máxima permitida por nodo.",
            )
            max_std_db = st.number_input(
                "Desviación estándar máxima de RSSI (dB)",
                min_value=0.0, max_value=50.0,
                value=float(config.get('max_std_db', 6.0)),
                step=0.5, format="%.1f",
                help="Desviación estándar máxima permitida por nodo.",
            )
            max_error_triangulos = st.number_input(
                "Error máximo de triángulos (m)",
                min_value=0.0, max_value=100.0,
                value=float(config.get('max_error_triangulos', 2.0)),
                step=0.1, format="%.1f",
                help="Si el error individual de triángulos supera este valor, "
                     "no se guarda esa estimación. Círculos se conserva.",
            )

            if st.button("💾 Guardar Configuración", type="primary", use_container_width=True):
                db.set_config("mqtt_broker", mqtt_broker)
                db.set_config("mqtt_port", mqtt_port)
                db.set_config("mqtt_user", mqtt_user)
                db.set_config("mqtt_password", mqtt_pass)
                db.set_config("n_pathloss", n_pathloss)
                db.set_config("n_muestras", n_muestras)
                db.set_config("max_iqr_db", max_iqr_db)
                db.set_config("max_std_db", max_std_db)
                db.set_config("max_error_triangulos", max_error_triangulos)
                st.success("✅ Configuración guardada. Reinicia el monitoreo para aplicar cambios MQTT.")
                st.rerun()

        with col2:
            st.markdown("### ℹ️ Estado del Sistema")
            manager = mqtt_manager.get_manager()
            estado = manager.get_estado()
            st.write(f"**MQTT Conectado:** {'✅ Sí' if estado['connected'] else '❌ No'}")
            st.write(f"**Área activa:** {estado['active_area']}")
            st.write(f"**Tópicos activos:** {len(estado['active_topics'])}")

            areas = db.listar_areas()
            total_esp = db.listar_esp32()
            st.write(f"**Áreas registradas:** {len(areas)}")
            st.write(f"**ESP32 registrados:** {len(total_esp)}")

        st.markdown("---")
        st.markdown("### 🧭 Contexto físico de captura")
        st.caption(
            "Las sesiones nuevas deben registrar campaña, orientación, entorno, "
            "layout y obstáculos. Reiniciar MQTT o Streamlit no crea una sesión física."
        )

        capture_area_map = {
            area["id"]: f"{area['nombre']} ({area['ancho']}×{area['alto']}m)"
            for area in areas
        }
        capture_area_id = st.selectbox(
            "Área de la campaña",
            options=list(capture_area_map),
            format_func=lambda value: capture_area_map[value],
            key="capture_context_area",
        )
        if capture_area_id is None:
            st.info("Crea un área en Administración antes de preparar una campaña.")
            st.stop()
        capture_area = db.obtener_area(capture_area_id)
        whole_width = abs(float(capture_area["ancho"]) - round(float(capture_area["ancho"]))) < 1e-9
        whole_height = abs(float(capture_area["alto"]) - round(float(capture_area["alto"]))) < 1e-9
        if whole_width and whole_height:
            fixed_positions = [
                [float(x), float(y)]
                for y in range(int(round(float(capture_area["alto"]))) + 1)
                for x in range(int(round(float(capture_area["ancho"]))) + 1)
            ]
        else:
            fixed_positions = []
            st.warning("El área no permite generar automáticamente la cuadrícula de 1 m.")

        campaigns = db.listar_campanas(capture_area_id)
        with st.expander("➕ Crear campaña física", expanded=not campaigns):
            with st.form("new_capture_campaign"):
                campaign_code = st.text_input("Código de campaña", placeholder="campaign-2026-03")
                campaign_description = st.text_input("Descripción de campaña")
                campaign_environment = st.text_area(
                    "Condiciones ambientales de la campaña",
                    placeholder="Sala despejada, puerta cerrada, sin obstáculos añadidos",
                )
                protocol_version = st.text_input("Versión del protocolo", value="capture-v1")
                st.caption(f"Orden fijo de posiciones ({len(fixed_positions)}): {fixed_positions}")
                create_campaign = st.form_submit_button("Crear campaña", type="primary")
            if create_campaign:
                try:
                    campaign_id = db.crear_campana(
                        area_id=capture_area_id,
                        codigo=campaign_code,
                        descripcion=campaign_description,
                        condiciones_ambientales=campaign_environment,
                        orden_posiciones=fixed_positions,
                        protocol_version=protocol_version,
                    )
                    st.success(f"Campaña creada (id={campaign_id}).")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

        campaigns = db.listar_campanas(capture_area_id)
        if campaigns:
            campaign_options = {
                campaign["id"]: f"{campaign['codigo']} — {campaign['descripcion']}"
                for campaign in campaigns
            }
            selected_campaign_id = st.selectbox(
                "Campaña activa para la próxima sesión",
                options=list(campaign_options),
                format_func=lambda value: campaign_options[value],
                key="capture_context_campaign",
            )
            open_sessions = db.listar_sesiones_captura(
                capture_area_id, campaign_id=selected_campaign_id, solo_abiertas=True
            )
            if open_sessions:
                session_options = {
                    session["id"]: (
                        f"Sesión {session['id']} — {session.get('orientation') or 'sin orientación'} — "
                        f"{session.get('environment_tag') or 'sin entorno'}"
                    )
                    for session in open_sessions
                }
                resume_session_id = st.selectbox(
                    "Reanudar sesión física abierta",
                    options=list(session_options),
                    format_func=lambda value: session_options[value],
                    key="capture_context_resume_session",
                )
                if st.button("Usar sesión existente", key="resume_capture_session"):
                    manager.asignar_sesion_captura(capture_area_id, resume_session_id)
                    st.success(f"Sesión física {resume_session_id} asociada al área.")
                    st.rerun()

            with st.form("new_physical_capture_session"):
                session_orientation = st.selectbox(
                    "Orientación del dispositivo",
                    ["north", "east", "south", "west", "unknown"],
                )
                session_environment = st.text_input(
                    "Etiqueta de entorno", value="baseline-v1"
                )
                session_layout = st.text_input(
                    "Versión del layout de anchors", value="layout-v1"
                )
                independence_evidence = st.text_area(
                    "Evidencia de independencia física",
                    placeholder="Horario distinto, recolocación del dispositivo y condiciones ambientales",
                )
                obstacle_description = st.text_area(
                    "Descripción detallada de obstáculos (o referencia fotográfica)",
                )
                obstacle_photo_ref = st.text_input(
                    "Referencia/hash de fotografía (opcional si hay descripción)",
                )
                operator_notes = st.text_area("Notas del operador (opcional)")
                open_session = st.form_submit_button("Abrir sesión física", type="primary")
            if open_session:
                try:
                    session_id = db.crear_sesion_captura(
                        campaign_id=selected_campaign_id,
                        area_id=capture_area_id,
                        orientation=session_orientation,
                        environment_tag=session_environment,
                        layout_version=session_layout,
                        independence_evidence=independence_evidence,
                        obstacle_description=obstacle_description,
                        obstacle_photo_ref=obstacle_photo_ref,
                        operator_notes=operator_notes,
                        node_schema_hash="|".join(
                            node["node_id"] for node in db.listar_esp32_por_area(capture_area_id)
                        ),
                    )
                    manager.asignar_sesion_captura(capture_area_id, session_id)
                    st.success(
                        f"Sesión física {session_id} abierta y asociada al área. "
                        "Los próximos ciclos normalizados usarán esta sesión."
                    )
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            active_session = manager.obtener_sesion_captura(capture_area_id)
            if active_session is not None:
                st.info(f"Sesión normalizada activa para el área: {active_session}")
                session_context = db.obtener_sesion_captura(active_session)
                if session_context and session_context.get("campaign_id"):
                    capture_positions = [
                        tuple(position)
                        for position in db.obtener_posiciones_campana(
                            session_context["campaign_id"]
                        )
                    ]
                    current_position = manager.obtener_posicion_captura(capture_area_id)
                    selected_position = st.selectbox(
                        "Posición real de captura para los próximos ciclos",
                        options=capture_positions,
                        index=(
                            capture_positions.index(current_position)
                            if current_position in capture_positions else 0
                        ),
                        format_func=lambda position: (
                            f"({position[0]:g}, {position[1]:g})"
                        ),
                        key=f"capture_position_{capture_area_id}",
                        help=(
                            "La posición se guarda como etiqueta de cada ciclo. "
                            "Cambiarla descarta solo la ventana RSSI pendiente."
                        ),
                    )
                    if st.button(
                        "Establecer posición de captura",
                        key="set_capture_position",
                        type="primary",
                    ):
                        try:
                            manager.asignar_posicion_captura(
                                capture_area_id, selected_position
                            )
                            st.success(
                                "Posición fijada; ya se pueden capturar ciclos con esta etiqueta."
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                    if current_position is None:
                        st.warning(
                            "No hay una posición de captura seleccionada. MQTT no guardará "
                            "ciclos hasta establecerla explícitamente."
                        )
                    else:
                        st.caption(
                            f"Posición activa: ({current_position[0]:g}, "
                            f"{current_position[1]:g})"
                        )
                else:
                    st.warning(
                        "La sesión activa no tiene una campaña con recorrido fijo; "
                        "no se puede seleccionar una posición de captura."
                    )
                if st.button("Cerrar sesión física", key="close_capture_session"):
                    db.cerrar_sesion(active_session)
                    manager.liberar_sesion_captura(capture_area_id)
                    st.success("Sesión física cerrada; los próximos ciclos requerirán otra sesión explícita.")
                    st.rerun()
        else:
            st.info("Crea una campaña antes de abrir una sesión física.")

    # ============================================================
    # PÁGINA: MONITOREO (Multi-área — Opción A)
    # ============================================================
    elif pagina == "🖥️ Monitoreo":

        # --- Selector de áreas (MULTIPLE) ---
        areas = db.listar_areas()
        if not areas:
            st.warning("⚠️ No hay áreas configuradas. Ve a Administración para crear una.")
            st.stop()

        area_map = {a['id']: f"{a['nombre']} ({a['ancho']}×{a['alto']}m)" for a in areas}

        # --- Barra de estado global ---
        manager = mqtt_manager.get_manager()
        estado_global = manager.get_estado()
        bar_cols = st.columns([2, 1, 1])
        with bar_cols[0]:
            selected_ids = st.multiselect(
                "Áreas a monitorear simultáneamente:",
                options=list(area_map.keys()),
                default=[list(area_map.keys())[0]],
                format_func=lambda x: area_map[x],
                help="Selecciona varias áreas para verlas en paralelo. Una sola conexión MQTT suscribe todos sus topics.",
            )
        with bar_cols[1]:
            mqtt_color = "🟢" if estado_global['connected'] else "🔴"
            st.metric("MQTT Broker", f"{mqtt_color} {'Conectado' if estado_global['connected'] else 'Desconectado'}")
        with bar_cols[2]:
            st.metric("Tópicos activos", estado_global['total_topics'])

        if not selected_ids:
            st.info("👆 Selecciona al menos un área para empezar a monitorear.")
            st.stop()

        # Filtrar solo áreas con >=3 ESP32
        valid_ids = []
        for aid in selected_ids:
            nodos = db.listar_esp32_por_area(aid)
            if len(nodos) < 3:
                st.error(f"⚠️ Área '{area_map[aid]}' tiene {len(nodos)}/3 ESP32. Se omite.")
            else:
                valid_ids.append(aid)

        if not valid_ids:
            st.warning("Ninguna de las áreas seleccionadas tiene 3 ESP32. Configura ESP32 en Administración.")
            st.stop()

        # --- Sincronizar MQTT: activar las válidas, desactivar las demás ---
        errores = manager.sincronizar_areas(valid_ids)
        for err in errores:
            st.warning(f"MQTT: {err}")

        # ============================================================
        # TARJETA: POSICIÓN ACTUAL DEL BEACON (tiempo real)
        # ============================================================
        st.markdown("### 📍 Posición actual del beacon")
        beacon_cols = st.columns(len(valid_ids))
        for i, aid in enumerate(valid_ids):
            with beacon_cols[i]:
                area_obj = db.obtener_area(aid)
                ad = manager.store.get(aid)
                # Última estimación del ciclo guardado. Si triángulos fue
                # descartado, el ciclo actual queda representado por círculos.
                pos_actual = None
                metodo_usado = None
                if ad and ad.get('latest_estimate'):
                    latest = ad['latest_estimate']
                    pos_actual = latest['position']
                    metodo_usado = "Triángulos" if latest['method'] == 'triangulos' else "Círculos"
                elif ad:
                    # Compatibilidad con stores creados antes de latest_estimate.
                    if ad['triang']:
                        pos_actual = ad['triang'][-1]
                        metodo_usado = "Triángulos"
                    elif ad['circulos']:
                        pos_actual = ad['circulos'][-1]
                        metodo_usado = "Círculos"

                with st.container(border=True):
                    st.markdown(f"**{area_obj['nombre']}**")
                    if pos_actual is not None:
                        px, py = pos_actual
                        xr, yr = _monitor_reference_position(manager, aid, area_obj)
                        err = mqtt_manager.distancia(pos_actual, (xr, yr))
                        # Métricas grandes X, Y
                        pos_metric_cols = st.columns(2)
                        with pos_metric_cols[0]:
                            st.metric("X estimada", f"{px:.2f} m")
                        with pos_metric_cols[1]:
                            st.metric("Y estimada", f"{py:.2f} m")
                        st.caption(f" método: {metodo_usado} | error vs real: {err:.2f} m")
                        # Progreso de muestras hacia la próxima estimación
                        if ad:
                            counts = [len(ad['rssi'].get(n['topic'], [])) for n in db.listar_esp32_por_area(aid)]
                            n_cfg = int(db.get_config("n_muestras", "10"))
                            total = sum(counts)
                            target = n_cfg * 3
                            st.progress(min(total / target, 1.0) if target else 0,
                                       text=f"muestras: {total}/{target}")
                    else:
                        st.info("⏳ Esperando estimación... (acumulando muestras)")
                        if ad:
                            counts = [len(ad['rssi'].get(n['topic'], [])) for n in db.listar_esp32_por_area(aid)]
                            n_cfg = int(db.get_config("n_muestras", "10"))
                            total = sum(counts)
                            target = n_cfg * 3
                            st.progress(min(total / target, 1.0) if target else 0,
                                       text=f"muestras: {total}/{target}")
        st.markdown("")

        # --- Panel lateral de visualización (compartido entre áreas) ---
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 🎨 Visualización")
        metodo = st.sidebar.radio("Método de estimación:", ["Triángulos", "Círculos", "Ambos"])

        colores = {"Rojo": "red", "Verde": "green", "Azul": "blue", "Naranja": "orange", "Negro": "black", "Morado": "purple"}
        marcadores = {"Círculo": "o", "Cruz": "x", "Cuadrado": "s", "Triángulo": "^", "Estrella": "*"}
        fuentes = {"Sans-serif": "sans-serif", "Monospace": "monospace", "Serif": "serif"}

        with st.sidebar.expander("📐 Diseño de Triángulos"):
            color_triang = st.selectbox("Color", list(colores.keys()), index=0, key="c_t")
            marcador_triang = st.selectbox("Marcador", list(marcadores.keys()), index=1, key="m_t")

        with st.sidebar.expander("⭕ Diseño de Círculos"):
            color_circulos = st.selectbox("Color", list(colores.keys()), index=1, key="c_c")
            marcador_circulos = st.selectbox("Marcador", list(marcadores.keys()), index=0, key="m_c")

        with st.sidebar.expander("📝 Formato de Gráfica"):
            fuente = st.selectbox("Tipografía", list(fuentes.keys()), index=0)
            tam_titulo = st.sidebar.slider("Tamaño del título", 10, 24, 16, key="tam_tit")
            tam_ejes = st.sidebar.slider("Tamaño de ejes", 8, 20, 12, key="tam_ej")
            mostrar_leyenda = st.sidebar.checkbox("Mostrar leyenda", value=True, key="ver_ley")

        # --- Controles comunes ---
        ctrl_cols = st.columns([1, 1, 1])
        with ctrl_cols[0]:
            auto_update = st.toggle("⏱️ Monitoreo en Tiempo Real", value=False)
        with ctrl_cols[1]:
            btn_actualizar = st.button("🔄 Actualizar Todo", use_container_width=True)
        with ctrl_cols[2]:
            btn_limpiar = st.button("🗑️ Limpiar Todas las Áreas", type="primary", use_container_width=True)

        if btn_limpiar:
            for aid in valid_ids:
                manager.store.clear(aid)
            st.rerun()

        # ============================================================
        # FUNCIÓN DE GRÁFICA PARAMETRIZADA POR ÁREA
        # ============================================================
        def generar_figura(area, nodos, area_data, compacta=False):
            xr, yr = _monitor_reference_position(manager, area['id'], area)
            ancho_a, alto_a = area['ancho'], area['alto']
            figsize = (5, 4) if compacta else (8, 6)
            fig, ax = plt.subplots(figsize=figsize)
            ax.set_aspect('equal')
            ax.set_xlim(-0.5, ancho_a + 0.5)
            ax.set_ylim(-0.5, alto_a + 0.5)

            font_titulos = {'fontsize': tam_titulo - 2 if compacta else tam_titulo,
                            'fontweight': 'bold', 'family': fuentes[fuente], 'color': '#333333'}
            font_ejes = {'fontsize': tam_ejes - 1 if compacta else tam_ejes,
                         'family': fuentes[fuente], 'color': '#555555'}

            markers_nodos = ['o', 's', '^']
            colors_nodos = ['#2874A6', '#117A65', '#B9770E']
            for i, n in enumerate(nodos):
                ax.scatter(n['pos_x'], n['pos_y'], color=colors_nodos[i % 3],
                          s=90 if compacta else 130, label=f"{n['node_id']}",
                          marker=markers_nodos[i % 3], zorder=5)
                ax.annotate(f"  {n['topic']}", (n['pos_x'], n['pos_y']),
                           fontsize=7 if compacta else 8, color='#555555')

            ax.scatter(xr, yr, color='#8E44AD', s=140 if compacta else 200,
                      label='Punto Real', marker='*', zorder=5)

            if area_data:
                if metodo in ["Triángulos", "Ambos"] and area_data['triang']:
                    xts, yts = zip(*area_data['triang'])
                    r = mqtt_manager.calcular_error(area_data['triang'], (xr, yr))
                    angles = np.linspace(0, 2 * np.pi, 100)
                    ax.plot((r*np.cos(angles))+xr, (r*np.sin(angles))+yr,
                           color='gray', ls='dashed', alpha=0.5)
                    ax.scatter(xts, yts, color=colores[color_triang],
                              marker=marcadores[marcador_triang],
                              s=60 if compacta else 80, alpha=0.7,
                              label='Est. Triángulos', zorder=4)

                if metodo in ["Círculos", "Ambos"] and area_data['circulos']:
                    xc, yc = zip(*area_data['circulos'])
                    r = mqtt_manager.calcular_error(area_data['circulos'], (xr, yr))
                    angles = np.linspace(0, 2 * np.pi, 100)
                    ax.plot((r*np.cos(angles))+xr, (r*np.sin(angles))+yr,
                           color='gray', ls='dashed', alpha=0.5)
                    ax.scatter(xc, yc, color=colores[color_circulos],
                              marker=marcadores[marcador_circulos],
                              s=60 if compacta else 80, alpha=0.7,
                              label='Est. Círculos', zorder=4)

            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#DDDDDD')
            ax.spines['bottom'].set_color('#DDDDDD')
            ax.set_xlabel("Distancia X (m)", fontdict=font_ejes)
            ax.set_ylabel("Distancia Y (m)", fontdict=font_ejes)
            ax.set_title(f"{area['nombre']}", fontdict=font_titulos, pad=15)
            if mostrar_leyenda:
                ax.legend(loc='upper right',
                         fontsize=8 if compacta else 10,
                         framealpha=0.9, edgecolor='#DDDDDD')
            ax.grid(True, linestyle='--', linewidth=0.5, color='#E5E8E8', zorder=0)
            return fig

        # ============================================================
        # RENDER SEGÚN NÚMERO DE ÁREAS
        # ============================================================
        n_muestras_cfg = int(db.get_config("n_muestras", "10"))

        # --- Caso 1 área: vista detallada (preserva el original) ---
        if len(valid_ids) == 1:
            area_id = valid_ids[0]
            area = db.obtener_area(area_id)
            nodos = db.listar_esp32_por_area(area_id)
            area_data = manager.store.get(area_id)
            xr, yr = _monitor_reference_position(manager, area_id, area)

            st.markdown(f"""<div style='background-color: #F8F9F9; padding: 1.5rem; border-radius: 10px;
                        margin-bottom: 2rem; box-shadow: 0 2px 5px rgba(0,0,0,0.05);'>
                <h2 style='color: #1F618D; margin: 0;'>📡 {area['nombre']}</h2>
                <p style='color: #5D6D7E; margin: 0;'>Dimensiones: {area['ancho']}×{area['alto']}m |
                   Punto real: ({xr}, {yr}) | ESP32: {len(nodos)}/3</p>
            </div>""", unsafe_allow_html=True)

            # Métricas
            err_t, err_c = 0.0, 0.0
            if area_data:
                if area_data['triang']:
                    err_t = mqtt_manager.calcular_error(area_data['triang'], (xr, yr))
                if area_data['circulos']:
                    err_c = mqtt_manager.calcular_error(area_data['circulos'], (xr, yr))

            m_cols = st.columns(2)
            with m_cols[0]:
                if metodo in ["Triángulos", "Ambos"] and area_data and area_data['triang']:
                    st.metric("Precisión (Triángulos)", f"{err_t:.2f} m",
                             delta="Óptimo" if err_t < 1.0 else "Requiere calibración",
                             delta_color="inverse")
            with m_cols[1]:
                if metodo in ["Círculos", "Ambos"] and area_data and area_data['circulos']:
                    st.metric("Precisión (Círculos)", f"{err_c:.2f} m",
                             delta="Óptimo" if err_c < 1.0 else "Requiere calibración",
                             delta_color="inverse")

            # Progreso de muestras
            if area_data:
                with st.expander("📊 Progreso de adquisición", expanded=True):
                    prog_cols = st.columns(len(nodos))
                    for i, n in enumerate(nodos):
                        with prog_cols[i]:
                            count = len(area_data['rssi'].get(n['topic'], []))
                            pct = int((count / n_muestras_cfg) * 100)
                            st.progress(pct / 100, text=f"{n['node_id']}: {count}/{n_muestras_cfg}")

            # Estadísticas
            if area_data and (area_data['triang'] or area_data['circulos']):
                st.markdown("### 📈 Estadísticas de Precisión")
                stat_cols = st.columns(4)

                def calc_stats(lista, real):
                    errs = [mqtt_manager.distancia(p, real) for p in lista]
                    return {'media': np.mean(errs), 'min': np.min(errs),
                            'max': np.max(errs), 'std': np.std(errs)}

                if area_data['triang']:
                    s = calc_stats(area_data['triang'], (xr, yr))
                    with stat_cols[0]: st.metric("Media (Triángulos)", f"{s['media']:.2f} m")
                    with stat_cols[1]: st.metric("Mín / Máx", f"{s['min']:.2f} / {s['max']:.2f} m")
                    with stat_cols[2]: st.metric("Desviación", f"{s['std']:.2f} m")
                    with stat_cols[3]: st.metric("Muestras", f"{len(area_data['triang'])}")

                if area_data['circulos']:
                    st.markdown("")
                    s = calc_stats(area_data['circulos'], (xr, yr))
                    c_cols = st.columns(4)
                    with c_cols[0]: st.metric("Media (Círculos)", f"{s['media']:.2f} m")
                    with c_cols[1]: st.metric("Mín / Máx", f"{s['min']:.2f} / {s['max']:.2f} m")
                    with c_cols[2]: st.metric("Desviación", f"{s['std']:.2f} m")
                    with c_cols[3]: st.metric("Muestras", f"{len(area_data['circulos'])}")

            # Gráfica + export
            show_graph = (auto_update or btn_actualizar or
                         (area_data and (area_data['triang'] or area_data['circulos'])))
            if show_graph:
                if area_data and (area_data['triang'] or area_data['circulos']):
                    fig = generar_figura(area, nodos, area_data, compacta=False)
                    st.pyplot(fig)
                    buf = io.BytesIO()
                    fig.savefig(buf, format="svg", bbox_inches='tight'); buf.seek(0)
                    st.download_button("📥 Exportar Gráfica (SVG)", data=buf,
                                      file_name=f"reporte_{area['nombre'].replace(' ', '_')}.svg",
                                      mime="image/svg+xml", use_container_width=True)
                else:
                    st.warning("⚠️ Adquiriendo telemetría. Esperando muestras de los sensores...")

        # --- Caso 2+ áreas: grid de tarjetas (VISTA SIMULTÁNEA) ---
        else:
            st.markdown(f"### 📊 Monitoreo paralelo — {len(valid_ids)} áreas activas")
            st.caption(f"Una sola conexión MQTT, {estado_global['total_topics']} tópicos suscritos en paralelo.")

            # Grid de 2 columnas: cada celda es una tarjeta de área
            for i in range(0, len(valid_ids), 2):
                pair = valid_ids[i:i+2]
                grid_cols = st.columns(2)
                for j, aid in enumerate(pair):
                    with grid_cols[j]:
                        area = db.obtener_area(aid)
                        nodos = db.listar_esp32_por_area(aid)
                        area_data = manager.store.get(aid)
                        xr, yr = _monitor_reference_position(manager, aid, area)

                        # Tarjeta contenedora
                        with st.container(border=True):
                            st.markdown(f"#### 📡 {area['nombre']}")
                            st.caption(f"{area['ancho']}×{area['alto']}m | Punto real ({xr},{yr}) | {len(nodos)}/3 ESP32")

                            # Métricas
                            err_t = err_c = 0.0
                            if area_data:
                                if area_data['triang']:
                                    err_t = mqtt_manager.calcular_error(area_data['triang'], (xr, yr))
                                if area_data['circulos']:
                                    err_c = mqtt_manager.calcular_error(area_data['circulos'], (xr, yr))
                            m_cols = st.columns(2)
                            with m_cols[0]:
                                if area_data and area_data['triang']:
                                    st.metric("Err. Triángulos", f"{err_t:.2f} m")
                            with m_cols[1]:
                                if area_data and area_data['circulos']:
                                    st.metric("Err. Círculos", f"{err_c:.2f} m")

                            # Mini-gráfico
                            if area_data and (area_data['triang'] or area_data['circulos']):
                                fig = generar_figura(area, nodos, area_data, compacta=True)
                                st.pyplot(fig)
                            else:
                                st.info("⏳ Esperando muestras...")

                            # Progreso de muestras compacto
                            if area_data:
                                for n in nodos:
                                    count = len(area_data['rssi'].get(n['topic'], []))
                                    pct = int((count / n_muestras_cfg) * 100)
                                    st.progress(pct / 100, text=f"{n['node_id']}: {count}/{n_muestras_cfg}")

        # ============ EXPORTACIÓN CSV COMBINADO (multi-área) ============
        st.markdown("---")
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(['area_id', 'area_nombre', 'metodo', 'x', 'y', 'error_m'])
        for aid in valid_ids:
            area = db.obtener_area(aid)
            ad = manager.store.get(aid)
            if not ad: continue
            xr, yr = _monitor_reference_position(manager, aid, area)
            if ad['triang']:
                for x, y in ad['triang']:
                    err = mqtt_manager.distancia((x, y), (xr, yr))
                    writer.writerow([aid, area['nombre'], 'triangulos', f"{x:.4f}", f"{y:.4f}", f"{err:.4f}"])
            if ad['circulos']:
                for x, y in ad['circulos']:
                    err = mqtt_manager.distancia((x, y), (xr, yr))
                    writer.writerow([aid, area['nombre'], 'circulos', f"{x:.4f}", f"{y:.4f}", f"{err:.4f}"])
        st.download_button("📊 Exportar todas las áreas (CSV)", data=csv_buffer.getvalue(),
                          file_name="datos_multiarea.csv", mime="text/csv")

        # ============ MOTOR DE TIEMPO REAL ============
        if auto_update:
            time.sleep(2)
            st.rerun()
