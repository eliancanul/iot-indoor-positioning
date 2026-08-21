"""
mqtt_manager.py — Motor MQTT dinámico para el Sistema de Posicionamiento IoT
Reemplaza las suscripciones fijas por suscripciones dinámicas basadas en la BD.

Flujo:
  1. Se selecciona un área en la UI
  2. El manager lee los ESP32 de esa área desde la BD
  3. Se desuscribe de los topics anteriores
  4. Se suscribe a los topics nuevos
  5. on_message procesa las lecturas usando la calibración de cada nodo
  6. Cuando hay n_muestras por nodo, calcula la posición y la guarda
"""

import paho.mqtt.client as mqtt
import math
import threading
import time
import uuid
import ssl
import os
from statistics import median
import database as db


DEFAULT_MAX_IQR_DB = 10.0
DEFAULT_MAX_STD_DB = 6.0


# ============================================================
# FUNCIONES MATEMÁTICAS (movidas aquí desde app.py)
# ============================================================

def disRSSI(rssi, A, n):
    """Convierte RSSI a distancia en metros usando el modelo log-distance path loss."""
    return 10 ** ((A - rssi) / (10 * n))


def validar_geometria_l(nodos, tolerancia=1e-6):
    """Valida 3 nodos en L: origen, nodo X y nodo Y; todos en metros."""
    if len(nodos) != 3:
        return False, "Se requieren exactamente 3 nodos para geometría L"
    origen, eje_x, eje_y = nodos
    if abs(origen['pos_x']) > tolerancia or abs(origen['pos_y']) > tolerancia:
        return False, "La geometría L requiere un nodo origen en (0,0)"
    if eje_x['pos_x'] <= tolerancia or abs(eje_x['pos_y']) > tolerancia:
        return False, "La geometría L requiere el segundo nodo sobre el eje X"
    if eje_y['pos_y'] <= tolerancia or abs(eje_y['pos_x']) > tolerancia:
        return False, "La geometría L requiere el tercer nodo sobre el eje Y"
    return True, None


def diagnostico_triangulos(d, nodos, area_bounds):
    """Explica un triángulo inválido sin convertirlo en una posición falsa."""
    if len(d) != 3 or any(not math.isfinite(value) or value < 0 for value in d):
        return {'method': 'triangulos', 'reason': 'invalid_distance_input'}
    x_axis, y_axis = nodos[1]['pos_x'], nodos[2]['pos_y']
    raw_x = (d[0] ** 2 - d[1] ** 2 + x_axis ** 2) / (2 * x_axis)
    raw_y = (d[0] ** 2 - d[2] ** 2 + y_axis ** 2) / (2 * y_axis)
    residual = abs(math.hypot(raw_x, raw_y) - d[0])
    width, height = area_bounds
    reason = 'incompatible_ranges' if residual > 1.5 else 'outside_area'
    return {'method': 'triangulos', 'reason': reason,
            'raw_x': raw_x, 'raw_y': raw_y, 'residual_m': residual}


def triangulos(d, nodos, area_bounds=None):
    """Trilateración cerrada para una geometría L; None si es incompatible."""
    ok, _ = validar_geometria_l(nodos)
    if not ok or len(d) != 3 or any(not math.isfinite(x) or x < 0 for x in d):
        return None
    x_axis, y_axis = nodos[1]['pos_x'], nodos[2]['pos_y']
    # Resta de ecuaciones de círculos, estable para el origen y los ejes.
    x = (d[0] ** 2 - d[1] ** 2 + x_axis ** 2) / (2 * x_axis)
    y = (d[0] ** 2 - d[2] ** 2 + y_axis ** 2) / (2 * y_axis)
    radial_residual = abs(math.hypot(x, y) - d[0])
    if radial_residual > 1.5:
        return None
    if area_bounds is not None:
        width, height = area_bounds
        if not (0 <= x <= width and 0 <= y <= height):
            return None
    return x, y


def circulos(d, nodos, area_bounds=None):
    """Mínimos cuadrados robustos, limitado al área física, no a los nodos."""
    if len(d) != len(nodos) or any(not math.isfinite(x) or x < 0 for x in d):
        return None
    if area_bounds is None:
        max_x = max(n['pos_x'] for n in nodos)
        max_y = max(n['pos_y'] for n in nodos)
    else:
        max_x, max_y = area_bounds
    if max_x <= 0 or max_y <= 0:
        return None
    def score(x, y):
        return sum(min((math.hypot(x - n['pos_x'], y - n['pos_y']) - dist) ** 2, 4.0)
                   for dist, n in zip(d, nodos))
    best_x, best_y, best_score = 0.0, 0.0, float('inf')
    step = max(max_x, max_y) / 50.0
    for _ in range(4):
        if best_score == float('inf'):
            x_min, x_max, y_min, y_max = 0.0, max_x, 0.0, max_y
        else:
            x_min, x_max = max(0.0, best_x - 5 * step), min(max_x, best_x + 5 * step)
            y_min, y_max = max(0.0, best_y - 5 * step), min(max_y, best_y + 5 * step)
        for ix in range(max(1, int((x_max - x_min) / step)) + 1):
            for iy in range(max(1, int((y_max - y_min) / step)) + 1):
                x, y = x_min + ix * step, y_min + iy * step
                s = score(x, y)
                if s < best_score:
                    best_x, best_y, best_score = x, y, s
        step /= 5.0
    return best_x, best_y

def quality_report(windows, max_iqr_db=DEFAULT_MAX_IQR_DB,
                   max_std_db=DEFAULT_MAX_STD_DB):
    """Evalúa estabilidad RSSI; no permite que ventanas muy ruidosas entren al dataset."""
    reasons, stats = [], []
    if len(windows) != 3 or any(not values for values in windows):
        return {'accepted': False, 'reasons': ['incomplete_readings'], 'stats': []}
    for values in windows:
        ordered = sorted(values)
        q1, q3 = ordered[len(ordered)//4], ordered[(3*len(ordered))//4]
        mean = sum(values) / len(values)
        std = (sum((v-mean)**2 for v in values) / len(values)) ** 0.5
        item = {'iqr_db': q3-q1, 'std_db': std, 'count': len(values)}
        stats.append(item)
        if item['iqr_db'] > max_iqr_db:
            reasons.append('high_iqr')
        if item['std_db'] > max_std_db:
            reasons.append('high_std')
    return {'accepted': not reasons, 'reasons': sorted(set(reasons)), 'stats': stats}


def distancia(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)


def calcular_error(lista, real):
    """Promedio de errores de distancia de una lista de puntos contra el punto real."""
    if not lista:
        return 0
    return sum(distancia(p, real) for p in lista) / len(lista)


def comparar_estimaciones(triangulos_est, circulos_est, punto_real,
                          max_error_triangulos):
    """Compara ambos métodos por separado y filtra solo una estimación.

    El error se calcula de forma independiente para cada método en cada ciclo.
    Círculos nunca se filtra por el error de triángulos: si la estimación de
    triángulos supera el umbral, se devuelve como ``None`` y círculos se
    conserva sin cambios.
    """
    comparativas = {
        'triangulos': {
            'estimate': triangulos_est,
            'error': (
                distancia(triangulos_est, punto_real)
                if triangulos_est is not None and punto_real is not None else None
            ),
        },
        'circulos': {
            'estimate': circulos_est,
            'error': (
                distancia(circulos_est, punto_real)
                if circulos_est is not None and punto_real is not None else None
            ),
        },
    }
    tri = comparativas['triangulos']
    tri_rejected = tri['error'] is not None and tri['error'] > max_error_triangulos
    return {
        'comparativas': comparativas,
        'estimates': {
            'triangulos': None if tri_rejected else triangulos_est,
            'circulos': circulos_est,
        },
        'triangle_rejected': tri_rejected,
    }


# ============================================================
# STORE DE DATOS POR ÁREA (thread-safe)
# ============================================================

class AreaDataStore:
    """
    Almacena las lecturas y coordenadas calculadas para cada área.
    Thread-safe porque on_message corre en el thread del MQTT loop.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._data = {}  # area_id → {rssi, triang, circulos, progreso}

    def init_area(self, area_id, topics):
        """Inicializa el store para un área con sus topics."""
        with self._lock:
            if area_id not in self._data:
                self._data[area_id] = {
                    'rssi': {t: [] for t in topics},
                    'rssi_timestamps': {t: [] for t in topics},
                    'triang': [],
                    'circulos': [],
                    'latest_estimate': None,
                }

    def get(self, area_id):
        with self._lock:
            return self._data.get(area_id, None)

    def clear_pending(self, area_id):
        """Descarta solo la ventana RSSI aún no convertida en un ciclo."""
        with self._lock:
            data = self._data.get(area_id)
            if data is None:
                return
            for topic, values in data.get('rssi', {}).items():
                values.clear()
                data.get('rssi_timestamps', {}).get(topic, []).clear()

    def clear(self, area_id):
        with self._lock:
            if area_id in self._data:
                d = self._data[area_id]
                for t in d['rssi']:
                    d['rssi'][t].clear()
                    d.get('rssi_timestamps', {}).get(t, []).clear()
                d['triang'].clear()
                d['circulos'].clear()
                d['latest_estimate'] = None

    def clear_all(self):
        with self._lock:
            self._data.clear()


# ============================================================
# MANAGER MQTT DINÁMICO (MULTI-ÁREA)
# ============================================================

class MQTTManager:
    """
    Maneja el cliente MQTT y las suscripciones dinámicas.

    Soporta MÚLTIPLES áreas activas simultáneamente: una sola conexión
    al broker, suscrita a los topics de todas las áreas activas. El
    callback _on_message enruta cada mensaje al área correcta usando
    el mapa topic → area_id.
    """

    def __init__(self):
        self.client = None
        self.active_areas = set()           # set de area_ids activos
        self.topic_to_area = {}             # topic → area_id (mapa inverso)
        self.areas_config = {}              # area_id → lista de dicts de nodos
        self.store = AreaDataStore()
        self.connected = False
        self.sample_counter = {}

        self.collection_sessions = {}  # area_id -> normalized collection session id
        self.capture_positions = {}    # area_id -> (x, y) selected for the next cycles

    def asignar_sesion_captura(self, area_id, session_id):
        """Asocia los ciclos nuevos de un área a una sesión física explícita."""
        if session_id is None:
            raise ValueError("session_id es obligatorio")
        session_id = int(session_id)
        session = db.obtener_sesion_captura(session_id)
        if session is None:
            raise ValueError("La sesión física no existe")
        if session["area_id"] != area_id:
            raise ValueError("La sesión física no pertenece al área indicada")
        if session["finished_at"] is not None:
            raise ValueError("La sesión física ya está cerrada")
        self.collection_sessions[area_id] = session_id
        # La posición debe confirmarse de nuevo al abrir/reanudar una sesión.
        self.capture_positions.pop(area_id, None)

    def asignar_posicion_captura(self, area_id, position):
        """Selecciona la posición fija que etiquetará los próximos ciclos.

        La selección es explícita y se limita al recorrido de la campaña de la
        sesión activa. Cambiarla descarta solo la ventana RSSI pendiente, nunca
        las estimaciones ni las muestras ya persistidas.
        """
        session_id = self.collection_sessions.get(area_id)
        if session_id is None:
            raise ValueError("Primero debe asociarse una sesión física")
        session = db.obtener_sesion_captura(session_id)
        if session is None:
            raise ValueError("La sesión física no existe")
        try:
            candidate = (float(position[0]), float(position[1]))
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError("La posición debe tener coordenadas x,y numéricas") from exc
        if len(position) != 2:
            raise ValueError("La posición debe tener coordenadas x,y")
        positions = db.obtener_posiciones_campana(session["campaign_id"])
        if not any(
            abs(candidate[0] - point[0]) <= 1e-9
            and abs(candidate[1] - point[1]) <= 1e-9
            for point in positions
        ):
            raise ValueError("La posición no pertenece al recorrido de la campaña")
        self.capture_positions[area_id] = candidate
        self.store.clear_pending(area_id)

    def obtener_posicion_captura(self, area_id):
        """Devuelve la posición fija seleccionada para los próximos ciclos."""
        return self.capture_positions.get(area_id)

    def obtener_sesion_captura(self, area_id):
        """Devuelve la sesión física activa del área, si existe."""
        return self.collection_sessions.get(area_id)

    def liberar_sesion_captura(self, area_id):
        """Deja de asociar nuevos ciclos del área a la sesión activa."""
        self.collection_sessions.pop(area_id, None)
        self.capture_positions.pop(area_id, None)

    # ---- Alias de compatibilidad hacia atrás (código legacy) ----
    @property
    def active_area(self):
        """Devuelve la primera área activa, o None (compat legacy)."""
        return sorted(self.active_areas)[0] if self.active_areas else None

    @property
    def active_topics(self):
        """Lista plana de todos los topics suscritos (compat legacy)."""
        return list(self.topic_to_area.keys())

    @property
    def nodos_config(self):
        """Lista de nodos del área activa (compat legacy)."""
        aid = self.active_area
        return self.areas_config.get(aid, []) if aid else []

    @staticmethod
    def _ordenar_nodos_geometria_L(nodos):
        """
        Reordena una lista de 3 nodos para respetar la geometría L que exigen
        triangulos()/circulos():
            nodos[0] = origen (0,0) → el nodo más cercano a (0,0)
            nodos[1] = eje X       → el que tenga pos_y ≈ 0 y pos_x mayor
            nodos[2] = eje Y       → el que tenga pos_x ≈ 0 y pos_y mayor

        Heurística robusta: de los 3 nodos, el origen es el más cercano a (0,0).
        De los 2 restantes, el del eje X es el que tiene mayor pos_x (y pos_y pequeña),
        y el del eje Y es el que tiene mayor pos_y (y pos_x pequeña).
        """
        if len(nodos) != 3:
            return nodos  # no hay nada que reordenar

        # Por distancia euclidiana al origen (0,0)
        def dist_origen(n):
            return (n['pos_x'] ** 2 + n['pos_y'] ** 2) ** 0.5

        copia = list(nodos)
        origen = min(copia, key=dist_origen)
        copia.remove(origen)

        # De los 2 restantes: el del eje X tiene mayor pos_x, el del eje Y mayor pos_y
        if copia[0]['pos_x'] >= copia[1]['pos_x']:
            eje_x, eje_y = copia[0], copia[1]
        else:
            eje_x, eje_y = copia[1], copia[0]

        return [origen, eje_x, eje_y]

    def _ensure_client(self):
        """Crea el cliente MQTT si no existe."""
        if self.client is not None:
            return
        broker = db.get_config("mqtt_broker", "192.168.2.2")
        port = int(db.get_config("mqtt_port", "1883"))
        user = db.get_config("mqtt_user", "")
        password = db.get_config("mqtt_password", "")

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set(user, password)
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        # --- Configurar TLS si el puerto es 8883 (MQTTS) ---
        if port == 8883:
            ca_path = os.path.join(os.path.dirname(__file__), "ca.crt")
            if not os.path.exists(ca_path):
                print(f"[MQTT] ERROR TLS: no se encuentra ca.crt en {ca_path}")
                self.connected = False
                return
            # Broker interno con CA autofirmada que no cumple key usage.
            # Mantener TLS cifrado, pero sin validar la cadena en esta LAN.
            ssl_context = ssl._create_unverified_context()
            self.client.tls_set_context(ssl_context)
            print(f"[MQTT] TLS configurado con ca.crt")

        try:
            self.client.connect(broker, port, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"[MQTT] Error conectando: {e}")
            self.connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = True
        print(f"[MQTT] Conectado al broker (code={reason_code})")
        # Re-suscribir a TODOS los topics activos (de todas las áreas)
        if self.topic_to_area:
            for t in self.topic_to_area:
                client.subscribe(t)
            print(f"[MQTT] Re-suscrito a {len(self.topic_to_area)} topics")

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False
        print("[MQTT] Desconectado del broker")

    def _on_message(self, client, userdata, msg):
        """Callback que procesa cada lectura RSSI entrante y la enruta al área."""
        try:
            topic = msg.topic
            rssi = int(msg.payload)

            if not (-100 < rssi < 0):
                return

            area_id = self.topic_to_area.get(topic)
            if area_id is None:
                return

            area_data = self.store.get(area_id)
            if area_data is None or topic not in area_data['rssi']:
                return

            n_muestras = int(db.get_config("n_muestras", "10"))

            if len(area_data['rssi'][topic]) < n_muestras:
                area_data['rssi'][topic].append(rssi)
                area_data['rssi_timestamps'][topic].append(time.time())

            area_topics = [n['topic'] for n in self.areas_config[area_id]]
            if all(len(area_data['rssi'][t]) >= n_muestras for t in area_topics):
                self._calcular_posicion(area_data, area_id, n_muestras)

        except Exception as e:
            print(f"[MQTT] Error procesando mensaje: {e}")

    def _calcular_posicion(self, area_data, area_id, n_muestras):
        """Calcula la posición estimada cuando hay suficientes muestras."""
        session_id = self.collection_sessions.get(area_id)
        context_required = db.get_config("capture_context_required", "1") == "1"
        if context_required and session_id is None:
            print(
                f"[CAPTURA] Área {area_id}: se requiere una sesión física explícita; "
                "el ciclo no se guarda."
            )
            self.store.clear_pending(area_id)
            return

        real = self.capture_positions.get(area_id)
        if context_required and real is None:
            print(
                f"[CAPTURA] Área {area_id}: se requiere seleccionar una posición "
                "del recorrido antes de guardar ciclos."
            )
            self.store.clear_pending(area_id)
            return
        if real is None:
            try:
                real = db.obtener_posicion_beacon(area_id)
            except Exception as e:
                print(f"[MQTT] Error obteniendo posición real del área {area_id}: {e}")
                real = None

        n_pathloss = float(db.get_config("n_pathloss", "3.223"))
        nodos = self.areas_config[area_id]

        raw_by_node = {}
        rssi_medianas = []
        promedio = []
        for n in nodos:
            t = n['topic']
            raw_values = list(area_data['rssi'][t])
            # Compatibilidad con buffers antiguos/pruebas creadas antes de que
            # existiera rssi_timestamps. En producción los tiempos se capturan
            # en _on_message; aquí solo se completa el caso ausente.
            timestamps_by_topic = area_data.get('rssi_timestamps', {})
            raw_timestamps = list(timestamps_by_topic.get(t, []))
            if len(raw_timestamps) != len(raw_values):
                raw_timestamps = [time.time()] * len(raw_values)
            raw_by_node[n['node_id']] = (raw_values, raw_timestamps)
            rssi_filtrado = median(raw_values)
            rssi_medianas.append(rssi_filtrado)
            n_nodo = n.get('n_pathloss') or n_pathloss
            d = disRSSI(rssi_filtrado, n['rssi_1m'], n_nodo)
            promedio.append(d)
            area_data['rssi'][t].clear()
            if t in area_data.get('rssi_timestamps', {}):
                area_data['rssi_timestamps'][t].clear()

        try:
            max_iqr_db = float(db.get_config('max_iqr_db', DEFAULT_MAX_IQR_DB))
        except (TypeError, ValueError):
            max_iqr_db = DEFAULT_MAX_IQR_DB
        try:
            max_std_db = float(db.get_config('max_std_db', DEFAULT_MAX_STD_DB))
        except (TypeError, ValueError):
            max_std_db = DEFAULT_MAX_STD_DB
        if max_iqr_db < 0:
            max_iqr_db = DEFAULT_MAX_IQR_DB
        if max_std_db < 0:
            max_std_db = DEFAULT_MAX_STD_DB

        quality = quality_report(
            [raw_by_node[n['node_id']][0] for n in nodos],
            max_iqr_db=max_iqr_db,
            max_std_db=max_std_db,
        )
        readings = [
            {
                "node_id": nodo["node_id"],
                "rssi_values": raw_by_node[nodo["node_id"]][0],
                "window_start_at": (
                    raw_by_node[nodo["node_id"]][1][0]
                    if raw_by_node[nodo["node_id"]][1] else None
                ),
                "captured_at": (
                    raw_by_node[nodo["node_id"]][1][-1]
                    if raw_by_node[nodo["node_id"]][1] else None
                ),
            }
            for nodo in nodos
        ]
        cycle_id = f"mqtt:{area_id}:{uuid.uuid4()}"

        if not quality['accepted']:
            print(f"[CAPTURA INVALIDA] razones={quality['reasons']} stats={quality['stats']}")
            for nodo in nodos:
                valores = raw_by_node[nodo['node_id']][0]
                print(f"[CAPTURA INVALIDA] {nodo['node_id']}: {valores}")
            invalid_quality = [
                {'method': 'capture_quality', 'reason': reason}
                for reason in quality['reasons']
            ]
            try:
                captured = db.guardar_ciclo_captura(
                    area_id=area_id,
                    session_id=session_id,
                    cycle_id=cycle_id,
                    x_real=real[0] if real else None,
                    y_real=real[1] if real else None,
                    readings=readings,
                    estimates={},
                    max_window_skew_s=float(db.get_config("max_window_skew_s", "20")),
                    invalid_estimates=invalid_quality,
                    quality_status="dirty",
                    quality_reasons=quality['reasons'],
                )
                if captured["saved"]:
                    self.collection_sessions[area_id] = captured["session_id"]
            except Exception as e:
                print(f"[CAPTURA] Error guardando muestra sucia: {e}")
            print("[CAPTURA INVALIDA] La muestra cruda se conservó para auditoría.")
            print("[CAPTURA INVALIDA] " + "-" * 60)
            return

        area = db.obtener_area(area_id)
        area_bounds = (area['ancho'], area['alto']) if area else None
        tri_raw = triangulos(promedio, nodos, area_bounds=area_bounds)
        circ = circulos(promedio, nodos, area_bounds=area_bounds)

        try:
            max_error_tri = float(db.get_config('max_error_triangulos', '2.0'))
        except (TypeError, ValueError):
            max_error_tri = 2.0
        if max_error_tri < 0:
            max_error_tri = 2.0

        # Cada ciclo produce dos comparativas independientes: una contra la
        # posición de triángulos y otra contra la de círculos. Solo se descarta
        # la estimación triangular si su propio error supera el umbral.
        comparison = comparar_estimaciones(tri_raw, circ, real, max_error_tri)
        tri = comparison['estimates']['triangulos']
        error_tri = comparison['comparativas']['triangulos']['error']
        error_circ = comparison['comparativas']['circulos']['error']

        invalid_estimates = []
        if tri_raw is None:
            invalid_estimates.append(diagnostico_triangulos(promedio, nodos, area_bounds))
        elif comparison['triangle_rejected']:
            invalid_estimates.append({
                'method': 'triangulos',
                'reason': 'high_error',
                'raw_x': tri_raw[0],
                'raw_y': tri_raw[1],
                'residual_m': error_tri,
            })
            print(f"[CAPTURA] Triángulos descartado por error alto: {error_tri:.3f} m "
                  f"(umbral={max_error_tri:.3f} m)")

        # La UI solo recibe estimaciones que se pueden guardar; círculos se
        # conserva aunque triángulos haya sido descartado.
        if tri is not None:
            area_data['triang'].append(tri)
        if circ is not None:
            area_data['circulos'].append(circ)

        self.sample_counter[area_id] = self.sample_counter.get(area_id, 0) + 1

        # El ciclo tiene identidad independiente de los RSSI y usa el instante
        # de cierre de cada ventana. Eso evita deduplicar capturas estacionarias válidas.
        try:
            captured = db.guardar_ciclo_captura(
                area_id=area_id,
                session_id=self.collection_sessions.get(area_id),
                cycle_id=cycle_id,
                x_real=real[0] if real else None,
                y_real=real[1] if real else None,
                readings=readings,
                estimates={"triangulos": tri, "circulos": circ},
                max_window_skew_s=float(db.get_config("max_window_skew_s", "2.0")),
                invalid_estimates=invalid_estimates,
            )
            if captured["saved"]:
                self.collection_sessions[area_id] = captured["session_id"]
                if tri is not None:
                    area_data['latest_estimate'] = {'method': 'triangulos', 'position': tri}
                elif circ is not None:
                    area_data['latest_estimate'] = {'method': 'circulos', 'position': circ}
                else:
                    area_data['latest_estimate'] = None
            else:
                print(f"[CAPTURA] Ciclo no guardado: {captured['reason']}")
                return
        except Exception as e:
            print(f"[CAPTURA] Error en guardado atómico: {e}")
            return

        # La tabla histórica se conserva por compatibilidad. Si una estimación
        # fue rechazada, se registra como NULL, nunca como coordenada inventada.
        try:
            db.guardar_dataset(
                area_id=area_id, experimento=1, muestra=self.sample_counter[area_id],
                rssi=rssi_medianas, dist=promedio, punto_real=real,
                triangulos={"x": tri[0] if tri else None, "y": tri[1] if tri else None, "error": error_tri},
                circulos={"x": circ[0] if circ else None, "y": circ[1] if circ else None, "error": error_circ},
                pathloss=n_pathloss, muestras_rssi=n_muestras, nodos=nodos,
            )
        except Exception as e:
            print(f"[DATASET] Error guardando fila histórica para área {area_id}: {e}")

        print(f"[MQTT] Área {area_id} posición calculada: triang={tri}, circulos={circ}")

    # ============================================================
    # API MULTI-ÁREA (nueva)
    # ============================================================

    def activar_area(self, area_id):
        """
        Suscribe los topics de un área SIN desactivar las demás.
        Retorna (True, None) si ok, (False, mensaje) si falla.
        """
        self._ensure_client()

        if area_id in self.active_areas:
            return True, None  # ya activa

        nodos = db.listar_esp32_por_area(area_id)
        if len(nodos) < 3:
            print(f"[MQTT] Área {area_id} tiene solo {len(nodos)} nodos (necesita 3)")
            return False, f"El área tiene solo {len(nodos)} ESP32 (necesita 3)"

        # Reordenar nodos para respetar la geometría L que exigen
        # triangulos()/circulos():
        #   nodos[0] = origen (0,0)
        #   nodos[1] = eje X (pos_y ≈ 0, pos_x > 0)
        #   nodos[2] = eje Y (pos_x ≈ 0, pos_y > 0)
        nodos = self._ordenar_nodos_geometria_L(nodos)
        geometria_ok, geometria_error = validar_geometria_l(nodos)
        if not geometria_ok:
            print(f"[MQTT] Área {area_id} con geometría inválida: {geometria_error}")
            return False, geometria_error

        self.active_areas.add(area_id)
        self.areas_config[area_id] = nodos

        topics = [n['topic'] for n in nodos]
        for t in topics:
            self.topic_to_area[t] = area_id

        self.store.init_area(area_id, topics)
        self.sample_counter.setdefault(area_id,0)

        if self.client and self.connected:
            for t in topics:
                self.client.subscribe(t)
            print(f"[MQTT] Área {area_id} suscrita a {len(topics)} topics: {topics}")

        return True, None

    def desactivar_area(self, area_id):
        """Desuscribe los topics de un área. No afecta a las demás."""
        if area_id not in self.active_areas:
            return True, None

        nodos = self.areas_config.get(area_id, [])
        topics = [n['topic'] for n in nodos]

        if self.client and self.connected:
            for t in topics:
                self.client.unsubscribe(t)

        for t in topics:
            self.topic_to_area.pop(t, None)

        self.active_areas.discard(area_id)
        self.areas_config.pop(area_id, None)
        self.capture_positions.pop(area_id, None)
        print(f"[MQTT] Área {area_id} desactivada ({len(topics)} topics retirados)")

        return True, None

    def sincronizar_areas(self, area_ids):
        """
        Sincroniza el set de áreas activas con una lista objetivo.
        Activa las que faltan, desactiva las que sobran.
        Útil para usar directo desde un st.multiselect.
        Retorna (ok, errores[]) donde errores es lista de mensajes de áreas que no se pudieron activar.
        """
        objetivo = set(area_ids)
        # Desactivar las que ya no están
        for aid in list(self.active_areas):
            if aid not in objetivo:
                self.desactivar_area(aid)
        # Activar las nuevas
        errores = []
        for aid in objetivo:
            if aid not in self.active_areas:
                ok, err = self.activar_area(aid)
                if not ok:
                    errores.append(err)
        return errores

    # ============================================================
    # API LEGACY (compat hacia atrás)
    # ============================================================

    def seleccionar_area(self, area_id):
        """
        Compatibilidad hacia atrás: desactiva todas las áreas y activa solo una.
        Equivale al comportamiento single-area original.
        """
        for other_id in list(self.active_areas):
            if other_id != area_id:
                self.desactivar_area(other_id)
        return self.activar_area(area_id)

    def get_estado(self):
        """Retorna el estado actual del manager para mostrar en la UI."""
        return {
            'connected': self.connected,
            'active_area': self.active_area,       # compat legacy
            'active_areas': sorted(self.active_areas),
            'active_topics': self.active_topics,    # compat legacy
            'total_topics': len(self.topic_to_area),
            'nodos': self.nodos_config,             # compat legacy
            'areas': {
                aid: [n['topic'] for n in nodos]
                for aid, nodos in self.areas_config.items()
            },
        }


# Singleton cached por Streamlit
_manager_instance = None

def get_manager():
    """Devuelve la instancia única del MQTTManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MQTTManager()
    return _manager_instance
