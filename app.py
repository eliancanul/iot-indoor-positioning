import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import paho.mqtt.client as mqtt
import math
import io
import time

# ============ CONFIGURACIÓN DE PÁGINA (Debe ser la línea 1) ============
st.set_page_config(page_title="Plataforma IoT | UQROO", page_icon="📡", layout="wide")

# ============ INYECCIÓN DE CSS PROFESIONAL ============
# Esto oculta elementos de Streamlit y moderniza los componentes
st.markdown("""
<style>
    /* Ocultar menú de hamburguesa, botón de deploy y footer de Streamlit */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Ajustar el espacio superior */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }

    /* Estilo moderno para los botones */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    /* Efecto de elevación al pasar el mouse por los botones */
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    
    /* Personalizar los números de las métricas de error */
    div[data-testid="stMetricValue"] {
        font-size: 2rem;
        color: #1F618D;
    }
</style>
""", unsafe_allow_html=True)

# ============ SISTEMA DE INICIO DE SESIÓN ============
if 'autenticado' not in st.session_state:
    st.session_state.autenticado = False

if not st.session_state.autenticado:
    # Espaciado para centrar el login verticalmente
    st.markdown("<div style='margin-top: 10vh;'></div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        # Encabezado del Login personalizado
        st.markdown("""
            <div style='text-align: center; padding: 1rem;'>
                <h1 style='color: #1F618D; margin-bottom: 0px; font-size: 2.8rem;'>📡 Plataforma IoT</h1>
                <p style='color: #7F8C8D; font-size: 1.2rem; margin-top: 5px;'>Sistema de Posicionamiento en Interiores</p>
                <hr style='border: 1px solid #EAECEE; margin-bottom: 25px;'>
            </div>
        """, unsafe_allow_html=True)
        
        # Campos de texto
        usuario = st.text_input("👤 Usuario", placeholder="Ingresa tu usuario")
        password = st.text_input("🔑 Contraseña", type="password", placeholder="••••••••")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Botón de ingreso
        if st.button("Ingresar al Sistema", use_container_width=True, type="primary"):
            if usuario == "admin" and password == "admin":
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("❌ Credenciales incorrectas. Verifique e intente nuevamente.")
        
        # Pie de página del login
        st.markdown("""
            <div style='text-align: center; margin-top: 40px;'>
                <small style='color: #BDC3C7;'>Estancia Profesional 2026 holaaa • UPA - UQROO</small>
            </div>
        """, unsafe_allow_html=True)

# ============ SI EL USUARIO ESTÁ AUTENTICADO, SE MUESTRA EL DASHBOARD ============
else:
    # ============ CONSTANTES Y CONFIGURACIÓN ============
    E0 = (0, 0)
    E1 = (4, 0)
    E2 = (0, 3)
    xr, yr = 2, 2  # Punto real

    MQTT_BROKER = '192.168.2.2'
    MQTT_PORT = 1883
    MQTT_USER = 'user'
    MQTT_PASSWORD = 'password'
    TOPICS = ['RSSI_0', 'RSSI_1', 'RSSI_2']

    RSSI_1m = [-62.5, -69.93, -65.08]
    n_pathloss = 3.223
    n_muestras = 10

    # ============ MEMORIA COMPARTIDA ============
    @st.cache_resource
    def get_data_store():
        return {
            'rssi_data': {t: [] for t in TOPICS},
            'coordenadas_triang': [],
            'coordenadas_circulos': []
        }

    store = get_data_store()

    # ============ FUNCIONES MATEMÁTICAS ============
    def disRSSI(rssi, A, n):
        return 10 ** ((A - rssi) / (10 * n))

    def coordTriangulo(a, b, c):
        if (a + b > c) and (a + c > b) and (b + c > a):
            beta = math.acos((b**2 + c**2 - a**2) / (2 * b * c))
            x = c * math.cos(beta)
            y = c * math.sin(beta)
        else:
            diff = b - (a + c)
            x = c + diff / 2
            y = 0
        return x, y

    def triangulos(d):
        x1, y1 = coordTriangulo(d[1], E1[0], d[0])
        y2, x2 = coordTriangulo(d[2], E2[1], d[0])
        if y1 == 0 or x2 == 0:
            return x1, y2
        return (x1 + x2) / 2, (y1 + y2) / 2

    def coordEjeCirculos(r1, r2, eje):
        return -(r2**2 - r1**2 - eje**2) / (2 * eje)

    def circulos(d):
        xc = coordEjeCirculos(d[0], d[1], E1[0])
        yc = coordEjeCirculos(d[0], d[2], E2[1])
        return (xc, yc)

    def distancia(p1, p2):
        return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

    def calcular_error(lista, real):
        if not lista:
            return 0
        return sum([distancia(p, real) for p in lista]) / len(lista)

    # ============ CLIENTE MQTT EN SEGUNDO PLANO ============
    def on_message(client, userdata, msg):
        try:
            topic = msg.topic
            rssi = int(msg.payload)
            print(f"{topic}: {rssi}")
            
            if -100 < rssi < 0 and topic in store['rssi_data']:
                if len(store['rssi_data'][topic]) < n_muestras:
                    store['rssi_data'][topic].append(rssi)
                
                if all(len(store['rssi_data'][t]) >= n_muestras for t in TOPICS):
                    promedio = []
                    for i, t in enumerate(TOPICS):
                        avg = sum(store['rssi_data'][t]) / n_muestras
                        d = disRSSI(avg, RSSI_1m[i], n_pathloss)
                        promedio.append(d)
                        store['rssi_data'][t].clear() 
                    
                    store['coordenadas_triang'].append(triangulos(promedio))
                    store['coordenadas_circulos'].append(circulos(promedio))
        except Exception as e:
            print(f"Error procesando mensaje: {e}")

    @st.cache_resource
    def iniciar_mqtt():
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
        client.on_message = on_message
        client.connect(MQTT_BROKER, MQTT_PORT, 1883)
        for t in TOPICS:
            client.subscribe(t)
        client.loop_start() 

    iniciar_mqtt()

    # ============ ENCABEZADO DEL DASHBOARD ============
    st.markdown("""
        <div style='background-color: #F8F9F9; padding: 1.5rem; border-radius: 10px; margin-bottom: 2rem; box-shadow: 0 2px 5px rgba(0,0,0,0.05);'>
            <h1 style='color: #1F618D; margin: 0;'>📡 Consola de Monitoreo IoT</h1>
            <p style='color: #5D6D7E; margin: 0;'>Visualización en tiempo real del Posicionamiento en Interiores</p>
        </div>
    """, unsafe_allow_html=True)

    # ============ PANEL LATERAL DE CONFIGURACIÓN ============
    st.sidebar.markdown("<h2 style='color: #1F618D;'>⚙️ Panel de Control</h2>", unsafe_allow_html=True)
    metodo = st.sidebar.radio("Método de estimación:", ["Triángulos", "Círculos", "Ambos"])

    st.sidebar.markdown("### 🎨 Personalización Visual")
    colores = {"Rojo": "red", "Verde": "green", "Azul": "blue", "Naranja": "orange", "Negro": "black", "Morado": "purple"}
    lineas = {"Línea continua": "-", "Punteada": ":", "Guiones": "--", "Guiones-puntos": "-."}
    marcadores = {"Círculo": "o", "Cruz": "x", "Cuadrado": "s", "Triángulo": "^", "Estrella": "*"}
    fuentes = {"Sans-serif": "sans-serif", "Monospace": "monospace", "Serif": "serif"}

    with st.sidebar.expander("📐 Diseño de Triángulos"):
        color_triang = st.selectbox("Color", list(colores.keys()), index=0, key="c_t")
        linea_triang = st.selectbox("Estilo de Línea", list(lineas.keys()), index=2, key="l_t")
        marcador_triang = st.selectbox("Marcador", list(marcadores.keys()), index=1, key="m_t")

    with st.sidebar.expander("⭕ Diseño de Círculos"):
        color_circulos = st.selectbox("Color", list(colores.keys()), index=1, key="c_c")
        linea_circulos = st.selectbox("Estilo de Línea", list(lineas.keys()), index=3, key="l_c")
        marcador_circulos = st.selectbox("Marcador", list(marcadores.keys()), index=0, key="m_c")

    with st.sidebar.expander("📝 Formato de Gráfica"):
        fuente = st.selectbox("Tipografía", list(fuentes.keys()), index=0)
        tam_titulo = st.slider("Tamaño del título", 10, 24, 16)
        tam_ejes = st.slider("Tamaño de ejes", 8, 20, 12)
        mostrar_leyenda = st.checkbox("Mostrar leyenda", value=True)

    # Botón para cerrar sesión en el panel lateral
    st.sidebar.markdown("---")
    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

    # ============ FUNCIÓN DE GRÁFICA ============
    def generar_figura():
        fig, ax = plt.subplots(figsize=(8, 6)) 
        ax.set_aspect('equal')
        ax.set_xlim(-0.5, 8.1)
        ax.set_ylim(-0.5, 6.1)

        font_titulos = {'fontsize': tam_titulo, 'fontweight': 'bold', 'family': fuentes[fuente], 'color': '#333333'}
        font_ejes = {'fontsize': tam_ejes, 'family': fuentes[fuente], 'color': '#555555'}

        ax.scatter(*E0, color='#2874A6', s=130, label='Nodo ESP32_0', marker='o', zorder=5)
        ax.scatter(*E1, color='#117A65', s=130, label='Nodo ESP32_1', marker='s', zorder=5)
        ax.scatter(*E2, color='#B9770E', s=130, label='Nodo ESP32_2', marker='^', zorder=5)
        ax.scatter(xr, yr, color='#8E44AD', s=200, label='Punto Real', marker='*', zorder=5)

        if metodo in ["Triángulos", "Ambos"] and store['coordenadas_triang']:
            xts, yts = zip(*store['coordenadas_triang'])
            r = calcular_error(store['coordenadas_triang'], (xr, yr))
            angles = np.linspace(0, 2 * np.pi, 100)
            ax.plot((r*np.cos(angles))+xr, (r*np.sin(angles))+yr, color='gray', ls='dashed', alpha=0.5)
            ax.scatter(xts, yts, color=colores[color_triang], marker=marcadores[marcador_triang], s=80, alpha=0.7, label='Est. Triángulos', zorder=4)

        if metodo in ["Círculos", "Ambos"] and store['coordenadas_circulos']:
            xc, yc = zip(*store['coordenadas_circulos'])
            r = calcular_error(store['coordenadas_circulos'], (xr, yr))
            angles = np.linspace(0, 2 * np.pi, 100)
            ax.plot((r*np.cos(angles))+xr, (r*np.sin(angles))+yr, color='gray', ls='dashed', alpha=0.5)
            ax.scatter(xc, yc, color=colores[color_circulos], marker=marcadores[marcador_circulos], s=80, alpha=0.7, label='Est. Círculos', zorder=4)

        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('#DDDDDD')
        ax.spines['bottom'].set_color('#DDDDDD')
        ax.set_xlabel("Distancia X (metros)", fontdict=font_ejes)
        ax.set_ylabel("Distancia Y (metros)", fontdict=font_ejes)
        ax.set_title("Mapa de Posicionamiento", fontdict=font_titulos, pad=20)
        
        if mostrar_leyenda:
            ax.legend(loc='upper right', fontsize=10, framealpha=0.9, edgecolor='#DDDDDD')
        ax.grid(True, linestyle='--', linewidth=0.5, color='#E5E8E8', zorder=0)
        
        return fig

    # ============ LAYOUT PRINCIPAL Y MÉTRICAS ============
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        st.info("📡 **Estado:** Sistema en línea recibiendo telemetría...")
        auto_update = st.toggle("⏱️ Monitoreo en Tiempo Real", value=False)
        btn_actualizar = st.button("🔄 Actualizar Gráfica", use_container_width=True)
        
        # Botón para limpiar la gráfica
        btn_limpiar = st.button("🗑️ Limpiar Historial", type="primary", use_container_width=True)

    # LÓGICA DEL BOTÓN LIMPIAR
    if btn_limpiar:
        store['coordenadas_triang'].clear()
        store['coordenadas_circulos'].clear()
        for t in TOPICS:
            store['rssi_data'][t].clear()
        st.rerun()

    # Calculamos los errores para mostrarlos como métricas
    err_t, err_c = 0.0, 0.0
    if store['coordenadas_triang']: err_t = calcular_error(store['coordenadas_triang'], (xr, yr))
    if store['coordenadas_circulos']: err_c = calcular_error(store['coordenadas_circulos'], (xr, yr))

    with col2:
        if metodo in ["Triángulos", "Ambos"] and store['coordenadas_triang']:
            st.metric(label="Precisión (Triángulos)", value=f"{err_t:.2f} m", delta="Óptimo" if err_t < 1.0 else "Requiere calibración", delta_color="inverse")

    with col3:
        if metodo in ["Círculos", "Ambos"] and store['coordenadas_circulos']:
            st.metric(label="Precisión (Círculos)", value=f"{err_c:.2f} m", delta="Óptimo" if err_c < 1.0 else "Requiere calibración", delta_color="inverse")

    st.markdown("<br>", unsafe_allow_html=True)

    # ============ RENDERIZADO DE GRÁFICA ============
    if auto_update or btn_actualizar or store['coordenadas_triang'] or store['coordenadas_circulos']:
        if store['coordenadas_triang'] or store['coordenadas_circulos']:
            
            g_col1, g_col2, g_col3 = st.columns([1, 4, 1])
            with g_col2:
                fig = generar_figura()
                st.pyplot(fig)
                
                buffer = io.BytesIO()
                fig.savefig(buffer, format="svg", bbox_inches='tight')
                buffer.seek(0)
                st.download_button(
                    label="📥 Exportar Gráfica de Análisis (SVG)",
                    data=buffer,
                    file_name="reporte_posicionamiento.svg",
                    mime="image/svg+xml",
                    use_container_width=True
                )
        else:
            st.warning("⚠️ Adquiriendo telemetría. Esperando alcanzar el umbral de 10 muestras por sensor...")

    # ============ MOTOR DE TIEMPO REAL ============
    if auto_update:
        time.sleep(2)
        st.rerun()
