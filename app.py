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

# ============ INICIALIZACIÓN DE BD ============
db.init_db()
db.cargar_datos_semilla()

# ============ CONFIGURACIÓN DE PÁGINA ============
st.set_page_config(page_title="Plataforma IoT | UQROO", page_icon="📡", layout="wide")

# ============ CSS ============
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
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
        ["🖥️ Monitoreo", "⚙️ Administración", "🔧 Configuración"]
    )

    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

    # ============================================================
    # PÁGINA: ADMINISTRACIÓN (FASE 3)
    # ============================================================
    if pagina == "⚙️ Administración":
        admin_panel.render_admin_panel()

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

            if st.button("💾 Guardar Configuración", type="primary", use_container_width=True):
                db.set_config("mqtt_broker", mqtt_broker)
                db.set_config("mqtt_port", mqtt_port)
                db.set_config("mqtt_user", mqtt_user)
                db.set_config("mqtt_password", mqtt_pass)
                db.set_config("n_pathloss", n_pathloss)
                db.set_config("n_muestras", n_muestras)
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

    # ============================================================
    # PÁGINA: MONITOREO (FASE 4 — Dashboard adaptativo)
    # ============================================================
    elif pagina == "🖥️ Monitoreo":

        # --- Selector de área ---
        areas = db.listar_areas()
        if not areas:
            st.warning("⚠️ No hay áreas configuradas. Ve a Administración para crear una.")
            st.stop()

        area_map = {a['id']: f"{a['nombre']} ({a['ancho']}×{a['alto']}m)" for a in areas}
        col_sel, col_info = st.columns([1, 2])
        with col_sel:
            area_id = st.selectbox(
                "Seleccionar área a monitorear:",
                options=list(area_map.keys()),
                format_func=lambda x: area_map[x],
            )
        with col_info:
            nodos = db.listar_esp32_por_area(area_id)
            if len(nodos) < 3:
                st.error(f"⚠️ Esta área tiene {len(nodos)}/3 ESP32. Necesita 3 para funcionar.")
            else:
                st.success(f"✅ {len(nodos)}/3 ESP32 activos en esta área.")

        area = db.obtener_area(area_id)
        nodos = db.listar_esp32_por_area(area_id)

        if len(nodos) < 3:
            st.info("Ve a **Administración** para asignar ESP32 a esta área.")
            st.stop()

        # --- Inicializar MQTT para esta área ---
        manager = mqtt_manager.get_manager()
        if manager.active_area != area_id:
            ok, err = manager.seleccionar_area(area_id)
            if not ok:
                st.warning(f"MQTT: {err}")

        area_data = manager.store.get(area_id)

        # --- Punto real y dimensiones del área ---
        xr, yr = area['punto_real_x'], area['punto_real_y']
        ancho_area, alto_area = area['ancho'], area['alto']

        # ============ ENCABEZADO ============
        st.markdown(f"""
            <div style='background-color: #F8F9F9; padding: 1.5rem; border-radius: 10px;
                        margin-bottom: 2rem; box-shadow: 0 2px 5px rgba(0,0,0,0.05);'>
                <h1 style='color: #1F618D; margin: 0;'>📡 {area['nombre']}</h1>
                <p style='color: #5D6D7E; margin: 0;'>
                   Dimensiones: {ancho_area}×{alto_area}m |
                   Punto real: ({xr}, {yr}) |
                   ESP32: {len(nodos)}/3
                </p>
            </div>
        """, unsafe_allow_html=True)

        # ============ PANEL LATERAL ============
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 🎨 Visualización")
        metodo = st.sidebar.radio("Método de estimación:", ["Triángulos", "Círculos", "Ambos"])

        colores = {"Rojo": "red", "Verde": "green", "Azul": "blue", "Naranja": "orange", "Negro": "black", "Morado": "purple"}
        lineas = {"Línea continua": "-", "Punteada": ":", "Guiones": "--", "Guiones-puntos": "-."}
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
            tam_titulo = st.slider("Tamaño del título", 10, 24, 16)
            tam_ejes = st.slider("Tamaño de ejes", 8, 20, 12)
            mostrar_leyenda = st.checkbox("Mostrar leyenda", value=True)

        # ============ FUNCIÓN DE GRÁFICA (ADAPTATIVA) ============
        def generar_figura():
            fig, ax = plt.subplots(figsize=(8, 6))
            ax.set_aspect('equal')
            ax.set_xlim(-0.5, ancho_area + 0.5)
            ax.set_ylim(-0.5, alto_area + 0.5)

            font_titulos = {'fontsize': tam_titulo, 'fontweight': 'bold', 'family': fuentes[fuente], 'color': '#333333'}
            font_ejes = {'fontsize': tam_ejes, 'family': fuentes[fuente], 'color': '#555555'}

            # Dibujar nodos desde la BD
            markers_nodos = ['o', 's', '^']
            colors_nodos = ['#2874A6', '#117A65', '#B9770E']
            for i, n in enumerate(nodos):
                ax.scatter(n['pos_x'], n['pos_y'], color=colors_nodos[i % 3],
                          s=130, label=f"{n['node_id']}", marker=markers_nodos[i % 3], zorder=5)
                ax.annotate(f"  {n['topic']}", (n['pos_x'], n['pos_y']), fontsize=8, color='#555555')

            # Punto real
            ax.scatter(xr, yr, color='#8E44AD', s=200, label='Punto Real', marker='*', zorder=5)

            # Estimaciones
            if area_data:
                if metodo in ["Triángulos", "Ambos"] and area_data['triang']:
                    xts, yts = zip(*area_data['triang'])
                    r = mqtt_manager.calcular_error(area_data['triang'], (xr, yr))
                    angles = np.linspace(0, 2 * np.pi, 100)
                    ax.plot((r*np.cos(angles))+xr, (r*np.sin(angles))+yr, color='gray', ls='dashed', alpha=0.5)
                    ax.scatter(xts, yts, color=colores[color_triang],
                              marker=marcadores[marcador_triang], s=80, alpha=0.7,
                              label='Est. Triángulos', zorder=4)

                if metodo in ["Círculos", "Ambos"] and area_data['circulos']:
                    xc, yc = zip(*area_data['circulos'])
                    r = mqtt_manager.calcular_error(area_data['circulos'], (xr, yr))
                    angles = np.linspace(0, 2 * np.pi, 100)
                    ax.plot((r*np.cos(angles))+xr, (r*np.sin(angles))+yr, color='gray', ls='dashed', alpha=0.5)
                    ax.scatter(xc, yc, color=colores[color_circulos],
                              marker=marcadores[marcador_circulos], s=80, alpha=0.7,
                              label='Est. Círculos', zorder=4)

            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#DDDDDD')
            ax.spines['bottom'].set_color('#DDDDDD')
            ax.set_xlabel("Distancia X (metros)", fontdict=font_ejes)
            ax.set_ylabel("Distancia Y (metros)", fontdict=font_ejes)
            ax.set_title(f"Mapa de Posicionamiento — {area['nombre']}", fontdict=font_titulos, pad=20)
            if mostrar_leyenda:
                ax.legend(loc='upper right', fontsize=10, framealpha=0.9, edgecolor='#DDDDDD')
            ax.grid(True, linestyle='--', linewidth=0.5, color='#E5E8E8', zorder=0)
            return fig

        # ============ LAYOUT PRINCIPAL ============
        col1, col2, col3 = st.columns([1, 1, 1])

        with col1:
            estado = manager.get_estado()
            if estado['connected']:
                st.info("📡 **Estado:** Conectado al broker MQTT")
            else:
                st.warning("📡 **Estado:** Desconectado del broker")
            auto_update = st.toggle("⏱️ Monitoreo en Tiempo Real", value=False)
            btn_actualizar = st.button("🔄 Actualizar Gráfica", use_container_width=True)
            btn_limpiar = st.button("🗑️ Limpiar Historial", type="primary", use_container_width=True)

        if btn_limpiar:
            manager.store.clear(area_id)
            st.rerun()

        # ============ FASE 6: Progreso de muestras + métricas ============
        err_t, err_c = 0.0, 0.0
        if area_data:
            if area_data['triang']:
                err_t = mqtt_manager.calcular_error(area_data['triang'], (xr, yr))
            if area_data['circulos']:
                err_c = mqtt_manager.calcular_error(area_data['circulos'], (xr, yr))

        with col2:
            if metodo in ["Triángulos", "Ambos"] and area_data and area_data['triang']:
                st.metric(
                    label="Precisión (Triángulos)",
                    value=f"{err_t:.2f} m",
                    delta="Óptimo" if err_t < 1.0 else "Requiere calibración",
                    delta_color="inverse"
                )

        with col3:
            if metodo in ["Círculos", "Ambos"] and area_data and area_data['circulos']:
                st.metric(
                    label="Precisión (Círculos)",
                    value=f"{err_c:.2f} m",
                    delta="Óptimo" if err_c < 1.0 else "Requiere calibración",
                    delta_color="inverse"
                )

        st.markdown("<br>", unsafe_allow_html=True)

        # ============ PROGRESO DE MUESTRAS (FASE 6) ============
        if area_data:
            n_muestras_cfg = int(db.get_config("n_muestras", "10"))
            with st.expander("📊 Progreso de adquisición de muestras", expanded=True):
                prog_cols = st.columns(len(nodos))
                for i, n in enumerate(nodos):
                    with prog_cols[i]:
                        count = len(area_data['rssi'].get(n['topic'], []))
                        pct = int((count / n_muestras_cfg) * 100)
                        st.progress(pct / 100, text=f"{n['node_id']}: {count}/{n_muestras_cfg}")

        # ============ ESTADÍSTICAS (FASE 6) ============
        if area_data and (area_data['triang'] or area_data['circulos']):
            st.markdown("### 📈 Estadísticas de Precisión")
            stat_cols = st.columns(4)

            def calc_stats(lista, real):
                errs = [mqtt_manager.distancia(p, real) for p in lista]
                return {
                    'media': np.mean(errs),
                    'min': np.min(errs),
                    'max': np.max(errs),
                    'std': np.std(errs),
                }

            if area_data['triang']:
                s = calc_stats(area_data['triang'], (xr, yr))
                with stat_cols[0]:
                    st.metric("Media (Triángulos)", f"{s['media']:.2f} m")
                with stat_cols[1]:
                    st.metric("Mín / Máx", f"{s['min']:.2f} / {s['max']:.2f} m")
                with stat_cols[2]:
                    st.metric("Desviación", f"{s['std']:.2f} m")
                with stat_cols[3]:
                    st.metric("Muestras", f"{len(area_data['triang'])}")

            if area_data['circulos']:
                st.markdown("")
                s = calc_stats(area_data['circulos'], (xr, yr))
                c_cols = st.columns(4)
                with c_cols[0]:
                    st.metric("Media (Círculos)", f"{s['media']:.2f} m")
                with c_cols[1]:
                    st.metric("Mín / Máx", f"{s['min']:.2f} / {s['max']:.2f} m")
                with c_cols[2]:
                    st.metric("Desviación", f"{s['max']:.2f} m")
                with c_cols[3]:
                    st.metric("Muestras", f"{len(area_data['circulos'])}")

        # ============ GRÁFICA + EXPORTACIÓN (FASE 6: CSV) ============
        show_graph = (auto_update or btn_actualizar or
                      (area_data and (area_data['triang'] or area_data['circulos'])))

        if show_graph:
            if area_data and (area_data['triang'] or area_data['circulos']):
                g_col1, g_col2, g_col3 = st.columns([1, 4, 1])
                with g_col2:
                    fig = generar_figura()
                    st.pyplot(fig)

                    # Export SVG
                    buffer = io.BytesIO()
                    fig.savefig(buffer, format="svg", bbox_inches='tight')
                    buffer.seek(0)
                    st.download_button(
                        label="📥 Exportar Gráfica (SVG)",
                        data=buffer,
                        file_name=f"reporte_{area['nombre'].replace(' ', '_')}.svg",
                        mime="image/svg+xml",
                        use_container_width=True
                    )

                    # Export CSV (FASE 6)
                    csv_buffer = io.StringIO()
                    writer = csv.writer(csv_buffer)
                    writer.writerow(['metodo', 'x', 'y', 'error_m'])
                    if area_data['triang']:
                        for x, y in area_data['triang']:
                            err = mqtt_manager.distancia((x, y), (xr, yr))
                            writer.writerow(['triangulos', f"{x:.4f}", f"{y:.4f}", f"{err:.4f}"])
                    if area_data['circulos']:
                        for x, y in area_data['circulos']:
                            err = mqtt_manager.distancia((x, y), (xr, yr))
                            writer.writerow(['circulos', f"{x:.4f}", f"{y:.4f}", f"{err:.4f}"])
                    st.download_button(
                        label="📊 Exportar Datos (CSV)",
                        data=csv_buffer.getvalue(),
                        file_name=f"datos_{area['nombre'].replace(' ', '_')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
            else:
                st.warning("⚠️ Adquiriendo telemetría. Esperando muestras de los sensores...")

        # ============ MOTOR DE TIEMPO REAL ============
        if auto_update:
            time.sleep(2)
            st.rerun()
