"""
calibration.py — Asistente de calibración para rssi_1m y n_pathloss.

Flujo guiado:
  PASO 1: Calibrar rssi_1m de cada nodo (RSSI a 1 metro de distancia)
  PASO 2: Calibrar n_pathloss (exponente de pérdida del entorno)

El usuario coloca el beacon a distancias conocidas, captura N lecturas,
y el asistente calcula automáticamente los valores óptimos y los guarda
en la BD.

Implementación:
  - Un colector temporal de muestras MQTT (no interfiere con el manager activo)
  - Usa la conexión del broker ya configurada en config_global
  - Calcula mediana (no media) para robustez contra outliers
"""

import streamlit as st
import paho.mqtt.client as mqtt
import statistics
import threading
import time
import math
import io
import os
import ssl
import database as db


# ============================================================
# COLECTOR DE MUESTRAS MQTT (temporal, no afecta al manager)
# ============================================================

class CalibrationCollector:
    """
    Cliente MQTT dedicado que escucha topics específicos y acumula
    sus lecturas. Thread-safe. Se crea y se destruye por sesión de
    calibración — no interfiere con el MQTTManager principal.
    """

    def __init__(self):
        self.client = None
        self._lock = threading.Lock()
        self._samples = {}  # topic -> list[int]
        self._target_topics = []
        self.connected = False

    def start(self, topics):
        """Conecta al broker y empieza a escuchar los topics dados."""
        self.stop()
        self._target_topics = list(topics)
        with self._lock:
            self._samples = {t: [] for t in topics}

        broker = db.get_config("mqtt_broker", "192.168.2.2")
        port = int(db.get_config("mqtt_port", "1883"))
        user = db.get_config("mqtt_user", "")
        password = db.get_config("mqtt_password", "")

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set(user, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        if port == 8883:
            ca_path = os.path.join(os.path.dirname(__file__), "ca.crt")
            # Broker interno con CA autofirmada que no cumple key usage.
            # Mantener TLS cifrado, pero sin validar la cadena en esta LAN.
            ssl_context = ssl._create_unverified_context()
            self.client.tls_set_context(ssl_context)

        try:
            self.client.connect(broker, port, 60)
            self.client.loop_start()
            # on_connect ocurre en el hilo MQTT. Esperar su confirmación evita
            # que Streamlit haga rerun y muestre un falso estado Inactivo.
            deadline = time.time() + 5.0
            while time.time() < deadline and not self.connected:
                time.sleep(0.05)
            return self.connected
        except Exception as e:
            st.error(f"No se pudo conectar al broker: {e}")
            self.connected = False
            return False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = True
        for t in self._target_topics:
            client.subscribe(t)

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False

    def _on_message(self, client, userdata, msg):
        try:
            rssi = int(msg.payload)
            if -120 < rssi < 0:
                with self._lock:
                    if msg.topic in self._samples:
                        self._samples[msg.topic].append(rssi)
        except ValueError:
            pass

    def get_counts(self):
        """Devuelve {topic: n_muestras} actuales."""
        with self._lock:
            return {t: len(v) for t, v in self._samples.items()}

    def get_samples(self, topic):
        """Devuelve la lista de muestras de un topic."""
        with self._lock:
            return list(self._samples.get(topic, []))

    def clear_topic(self, topic):
        """Limpia las muestras de un topic específico."""
        with self._lock:
            if topic in self._samples:
                self._samples[topic] = []

    def clear_all(self):
        with self._lock:
            for t in self._samples:
                self._samples[t] = []

    def stop(self):
        """Desconecta y libera el cliente."""
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self.connected = False


# Singleton cached por sesión de Streamlit
_collector_instance = None


def get_collector():
    global _collector_instance
    if _collector_instance is None:
        _collector_instance = CalibrationCollector()
    return _collector_instance


# ============================================================
# FUNCIONES DE CÁLCULO
# ============================================================

def calc_rssi_1m(samples):
    """
    Dada una lista de lecturas RSSI tomadas a 1 metro de distancia,
    devuelve el valor representativo. Usamos mediana (robusta a outliers).
    """
    if not samples:
        return None
    return statistics.median(samples)


import math
import statistics


def fit_pathloss_per_node(measurements):
    """Ajusta RSSI=A-10*n*log10(d) por regresión lineal para un único nodo."""
    points = [(math.log10(float(d)), float(r)) for d, r in measurements if float(d) > 0]
    if len(points) < 2 or len({x for x, _ in points}) < 2:
        return None
    xbar = sum(x for x, _ in points) / len(points)
    ybar = sum(y for _, y in points) / len(points)
    denominator = sum((x - xbar) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    slope = sum((x - xbar) * (y - ybar) for x, y in points) / denominator
    n = -slope / 10.0
    A = ybar - slope * xbar
    residuals = [y - (A + slope*x) for x, y in points]
    rmse = (sum(r*r for r in residuals) / len(residuals)) ** 0.5
    if not (1.0 <= n <= 10.0):
        return None
    return {'rssi_1m': A, 'n_pathloss': n, 'rmse_db': rmse, 'point_count': len(points)}

def calc_n_pathloss(rssi_1m, measurements):
    """
    Dado el rssi_1m (de un nodo) y una lista de (distancia_real, rssi_medido),
    calcula el n_pathloss óptimo por regresión.

    Modelo: distancia = 10^((rssi_1m - rssi_medido) / (10 * n))
    Despejando n: n = (rssi_1m - rssi_medido) / (10 * log10(distancia))

    Promediamos n sobre todas las mediciones.
    """
    if not measurements or rssi_1m is None:
        return None
    ns = []
    for distancia, rssi_medido in measurements:
        if distancia > 0:
            n = (rssi_1m - rssi_medido) / (10 * math.log10(distancia))
            ns.append(n)
    if not ns:
        return None
    return statistics.median(ns)


def predict_distance(rssi_1m, rssi_measured, n):
    """Predice distancia en metros dados los parámetros calibrados."""
    if rssi_1m is None or n is None or n == 0:
        return None
    return 10 ** ((rssi_1m - rssi_measured) / (10 * n))


def calc_n_pathloss_auto(nodos, punto_real, lecturas):
    """
    Cálculo AUTOMÁTICO de n_pathloss usando la geometría conocida del área.

    No requiere que el usuario mida distancias a mano: aprovecha que las
    posiciones de los nodos (pos_x, pos_y) y el punto real son datos conocidos
    en la BD.

    Args:
        nodos:       lista de dicts con {node_id, pos_x, pos_y, rssi_1m, topic}
        punto_real:  tupla (x, y) con la posición real del beacon
        lecturas:    dict {topic: [rssi, rssi, ...]} capturadas mientras el
                     beacon estaba en punto_real

    Returns:
        dict con:
          - n_optimo:     valor recomendado para n_pathloss (mediana)
          - n_por_nodo:   {node_id: n_calculado} para diagnóstico
          - distancias:   {node_id: distancia_m} usada en el cálculo
          - confiable:    True si los 3 nodos dieron n razonable (1.5-6.0)
    """
    xr, yr = punto_real
    n_por_nodo = {}
    distancias = {}

    for nodo in nodos:
        topic = nodo['topic']
        muestras = lecturas.get(topic, [])
        if not muestras or nodo['rssi_1m'] is None:
            continue

        # Distancia geométrica exacta nodo → punto real
        dx = nodo['pos_x'] - xr
        dy = nodo['pos_y'] - yr
        d = math.sqrt(dx * dx + dy * dy)
        if d < 0.1:  # nodo pegado al punto real → división inestable
            continue

        distancias[nodo['node_id']] = d

        # RSSI medido representativo (mediana)
        rssi_med = statistics.median(muestras)

        # n = (rssi_1m - rssi_med) / (10 * log10(d))
        n = (nodo['rssi_1m'] - rssi_med) / (10 * math.log10(d))
        n_por_nodo[nodo['node_id']] = n

    if not n_por_nodo:
        return None

    # Filtrar valores fuera de rango razonable (1.5-6.0)
    valores_validos = [n for n in n_por_nodo.values() if 1.5 <= n <= 6.0]
    confiable = len(valores_validos) >= 2  # al menos 2 nodos dieron n razonable

    n_optimo = statistics.median(valores_validos) if valores_validos else None

    return {
        'n_optimo': n_optimo,
        'n_por_nodo': n_por_nodo,
        'distancias': distancias,
        'confiable': confiable,
    }


# ============================================================
# UI: PANEL DE CALIBRACIÓN
# ============================================================

def render_calibration_panel():
    """Renderiza el panel completo de calibración en la UI."""

    st.markdown("## 🔬 Calibración del Sistema")
    st.markdown("Calibra los parámetros que controlan la precisión del posicionamiento.")
    st.markdown("---")

    # Intro / instrucciones
    with st.expander("📖 Cómo funciona la calibración (lee esto primero)", expanded=False):
        st.markdown("""
**La precisión depende de 2 parámetros por cada nodo:**

1. **`rssi_1m`** — El RSSI medido a exactamente 1 metro de distancia del nodo.
   Cada ESP32 tiene el suyo propio (diferencias de antena, fabricación).

2. **`n_pathloss`** — Exponente de pérdida de señal del entorno (común a todos).
   Depende de las paredes, muebles, personas del cuarto. Rango típico: 2.0 (libre) a 4.5 (obstruido).

**Procedimiento recomendado:**
- Coloca el beacon a 1 m del nodo, captura 30 lecturas → obtienes `rssi_1m`
- Repite para los 3 nodos
- Luego mide a varias distancias (2m, 3m, 4m) → obtienes `n_pathloss`

**Tip:** Usa el **método de la mediana** (lo hace el sistema automáticamente) para ignorar picos espurios.
""")

    # ---------- Selector de área ----------
    areas = db.listar_areas()
    if not areas:
        st.warning("Primero crea un área en Administración.")
        return

    area_map = {a['id']: f"{a['nombre']} ({a['ancho']}×{a['alto']}m)" for a in areas}
    area_id = st.selectbox(
        "Área a calibrar:",
        options=list(area_map.keys()),
        format_func=lambda x: area_map[x],
    )

    nodos = db.listar_esp32_por_area(area_id)
    if len(nodos) < 3:
        st.warning(f"Esta área tiene {len(nodos)} ESP32 (necesita 3).")
        return

    collector = get_collector()
    topics = [n['topic'] for n in nodos]

    # ---------- Estado del colector ----------
    col_state1, col_state2 = st.columns(2)
    with col_state1:
        broker = db.get_config("mqtt_broker", "?")
        st.metric("Broker MQTT", broker)
    with col_state2:
        st.metric("Colector", "🟢 Activo" if collector.connected else "🔴 Inactivo")

    st.markdown("---")

    # ============================================================
    # PASO 1: Calibrar rssi_1m por nodo
    # ============================================================
    st.markdown("### PASO 1 — Calibrar `rssi_1m` (RSSI a 1 metro)")

    st.info("📍 **Instrucción:** Coloca el beacon a **1 metro exacto** de cada ESP32, "
            "uno por uno. Captura ~30 lecturas por nodo.")

    target_count = st.number_input(
        "Muestras a capturar por nodo:", min_value=10, max_value=100, value=30, step=5,
        help="Más muestras = mayor robustez, pero más tiempo de espera."
    )

    if st.button("🚀 Iniciar captura", type="primary", key="btn_start_rssi1m"):
        if collector.start(topics):
            st.success(f"Colector activo. Escuchando {len(topics)} topics: {topics}")
            st.rerun()
        else:
            st.error("El colector no confirmó conexión MQTT en 5 segundos.")

    # ---------- Tabla de captura por nodo ----------
    st.markdown("#### Avance de captura")

    # El callback MQTT corre en un hilo aparte. Este fragmento refresca los
    # contadores cada segundo sin reiniciar el colector ni persistir muestras.
    if collector.connected:
        @st.fragment(run_every="1s")
        def render_live_capture_status():
            live_counts = collector.get_counts()
            live_cols = st.columns(len(nodos))
            for col, nodo in zip(live_cols, nodos):
                live_count = live_counts.get(nodo["topic"], 0)
                with col:
                    st.metric(nodo["node_id"], f"{live_count}/{target_count} lecturas")
                    st.progress(min(live_count / target_count, 1.0))
        render_live_capture_status()

    counts = collector.get_counts() if collector.connected else {t: 0 for t in topics}

    for n in nodos:
        topic = n['topic']
        count = counts.get(topic, 0)
        pct = min(count / target_count, 1.0) if target_count else 0
        samples = collector.get_samples(topic)

        with st.container(border=True):
            cols = st.columns([2, 2, 1, 1, 1])
            with cols[0]:
                st.markdown(f"**{n['node_id']}** (`{topic}`)")
                st.caption(f"rssi_1m actual: {n['rssi_1m']}")
            with cols[1]:
                st.progress(pct, text=f"{count}/{target_count} muestras")
            with cols[2]:
                if samples:
                    st.metric("Mediana", f"{statistics.median(samples):.1f}")
                else:
                    st.metric("Mediana", "—")
            with cols[3]:
                if st.button("Calcular y guardar", key=f"save_{topic}", type="primary"):
                    if count >= 5:
                        nuevo = calc_rssi_1m(samples)
                        db.actualizar_esp32(
                            n['id'], n['node_id'], n['topic'],
                            n['pos_x'], n['pos_y'], nuevo, n['area_id']
                        )
                        st.success(f"✅ {n['node_id']}: rssi_1m = {nuevo:.2f} (guardado)")
                        collector.clear_topic(topic)
                        st.rerun()
                    else:
                        st.error(f"Necesitas al menos 5 muestras (tienes {count})")
            with cols[4]:
                if st.button("Limpiar", key=f"clear_{topic}"):
                    collector.clear_topic(topic)
                    st.rerun()

    if st.button("🛑 Detener colector", key="btn_stop_rssi1m"):
        collector.stop()
        st.rerun()

    st.markdown("---")

    # ============================================================
    # PASO 2: Calibrar n_pathloss por nodo
    # ============================================================
    st.markdown("### PASO 2 — Calibrar `n_pathloss` por ESP32")
    st.caption("Cada nodo recibe su propio exponente. El valor global queda solo como respaldo para nodos aún no calibrados.")

    st.info("📍 **Instrucción:** Coloca el beacon a varias distancias conocidas de un nodo. "
            "Registra distancia + RSSI medido. El sistema calculará el n óptimo.")

    # Formulario para añadir mediciones manuales
    nodos_for_select = {n['node_id']: n for n in nodos}
    n_sel = st.selectbox("Nodo de referencia:", options=list(nodos_for_select.keys()))
    nodo_ref = nodos_for_select[n_sel]

    # Mediciones separadas por nodo: nunca mezclar perfiles de antena distintos.
    measurement_key = f'pathloss_measurements_{nodo_ref["id"]}'
    if measurement_key not in st.session_state:
        st.session_state[measurement_key] = []

    col_d, col_r, col_add = st.columns([1, 1, 1])
    with col_d:
        new_dist = st.number_input("Distancia (m):", min_value=0.5, max_value=20.0, value=2.0, step=0.5)
    with col_r:
        new_rssi = st.number_input("RSSI medido (dBm):", min_value=-110.0, max_value=-10.0, value=-70.0, step=0.5)
    with col_add:
        st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
        if st.button("➕ Añadir medición", key="add_pathloss"):
            st.session_state[measurement_key].append((float(new_dist), float(new_rssi)))
            st.success(f"Añadida: {new_dist}m → {new_rssi} dBm")
            st.rerun()

    # Mostrar tabla de mediciones
    measurements = st.session_state[measurement_key]
    if measurements:
        st.markdown("#### Mediciones registradas")
        for i, (d, r) in enumerate(measurements):
            m_cols = st.columns([1, 1, 1])
            with m_cols[0]:
                st.text(f"{d:.1f} m")
            with m_cols[1]:
                st.text(f"{r:.1f} dBm")
            with m_cols[2]:
                if st.button("🗑", key=f"del_pathloss_{i}"):
                    st.session_state[measurement_key].pop(i)
                    st.rerun()

        # Calcular n_pathloss óptimo
        if len(measurements) >= 2:
            fit = fit_pathloss_per_node(measurements)
            if fit:
                st.success(f"📊 **{nodo_ref['node_id']}**: RSSI@1m={fit['rssi_1m']:.2f} dBm, "
                          f"n={fit['n_pathloss']:.3f}, RMSE={fit['rmse_db']:.2f} dB")
                if st.button("💾 Guardar calibración del nodo", type="primary", key=f"save_node_fit_{nodo_ref['id']}"):
                    db.actualizar_calibracion_nodo(nodo_ref['id'], rssi_1m=fit['rssi_1m'], n_pathloss=fit['n_pathloss'])
                    st.success(f"Guardada calibración individual de {nodo_ref['node_id']}")
                    st.rerun()
            else:
                st.warning("No se pudo ajustar una calibración válida. Usa al menos dos distancias diferentes y revisa las lecturas.")
    else:
        st.info("Añade al menos 2 mediciones para calcular n_pathloss.")

    if st.button("🧹 Limpiar mediciones", key="clear_pathloss"):
        st.session_state[measurement_key] = []
        st.rerun()

    st.markdown("---")

    # ============================================================
    # PASO 3 (automático): Calibrar n_pathloss usando el punto real
    # ============================================================
    st.markdown("### PASO 3 — Calibración automática de `n_pathloss`")

    area_obj = db.obtener_area(area_id)
    pr = (area_obj['punto_real_x'], area_obj['punto_real_y'])

    st.success(
        f"📍 **Coloca el beacon en el punto real marcado del suelo "
        f"({pr[0]:.2f}, {pr[1]:.2f})** y deja que el sistema capture muestras. "
        f"Se calcula `n_pathloss` automáticamente usando las distancias "
        f"geométricas conocidas de cada nodo al punto real."
    )

    # Tabla de distancias que se usarán
    with st.expander("📐 Distancias geométricas nodo → punto real", expanded=False):
        for n in nodos:
            d = math.sqrt((n['pos_x'] - pr[0])**2 + (n['pos_y'] - pr[1])**2)
            st.write(f"**{n['node_id']}** ({n['pos_x']}, {n['pos_y']}) → punto real: "
                    f"**{d:.2f} m**")

    # Usar el mismo colector del PASO 1 (compartido)
    auto_target = st.number_input(
        "Muestras por nodo (auto):", min_value=10, max_value=100, value=20, step=5,
        key="auto_target_n",
        help="Cuantas más muestras, más estable será el cálculo."
    )

    auto_cols = st.columns([1, 1, 1])
    with auto_cols[0]:
        if st.button("🚀 Iniciar captura automática", type="primary", key="btn_start_auto"):
            collector.start(topics)
            st.rerun()
    with auto_cols[1]:
        if st.button("🧮 Calcular n_pathloss", key="btn_calc_auto"):
            st.session_state['auto_calc_pending'] = True
            st.rerun()
    with auto_cols[2]:
        if st.button("🛑 Detener", key="btn_stop_auto"):
            collector.stop()
            st.rerun()

    # Avance de captura automática
    if collector.connected:
        counts = collector.get_counts()
        lecturas = {t: collector.get_samples(t) for t in topics}
        min_count = min((counts.get(t, 0) for t in topics), default=0)
        progreso = min(min_count / auto_target, 1.0) if auto_target else 0
        st.progress(progreso, text=f"Mínimo por nodo: {min_count}/{auto_target}")

        # Calcular si se solicitó y hay suficientes muestras
        if st.session_state.get('auto_calc_pending'):
            if min_count >= 5:
                resultado = calc_n_pathloss_auto(nodos, pr, lecturas)
                st.session_state['auto_calc_pending'] = False

                if resultado and resultado['n_optimo'] is not None:
                    st.success(f"✅ **n_pathloss óptimo: {resultado['n_optimo']:.3f}** "
                              f"({'confiable' if resultado['confiable'] else 'revisar'})")

                    # Tabla de diagnóstico
                    diag_rows = []
                    for nid, n_val in resultado['n_por_nodo'].items():
                        d = resultado['distancias'].get(nid, None)
                        flag = "✅" if 1.5 <= n_val <= 6.0 else "⚠️ fuera de rango"
                        diag_rows.append({
                            'Nodo': nid,
                            'Distancia (m)': f"{d:.2f}" if d else "—",
                            'n calculado': f"{n_val:.3f}",
                            'Estado': flag,
                        })
                    st.dataframe(diag_rows, use_container_width=True, hide_index=True)

                    if not resultado['confiable']:
                        st.warning("Menos de 2 nodos dieron un n razonable. "
                                  "Probablemente algún `rssi_1m` esté mal calibrado "
                                  "(revisa el PASO 1).")

                    if st.button("💾 Guardar n_pathloss en BD", type="primary", key="save_auto_n"):
                        db.set_config("n_pathloss", f"{resultado['n_optimo']:.3f}")
                        st.success(f"Guardado: n_pathloss = {resultado['n_optimo']:.3f}")
                        st.rerun()
                else:
                    st.error("No se pudo calcular n_pathloss. Verifica que los nodos "
                             "tengan `rssi_1m` calibrado (PASO 1) y que haya muestras suficientes.")
            else:
                st.warning(f"Se necesitan al menos 5 muestras por nodo (mínimo actual: {min_count}).")
