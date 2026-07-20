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
import database as db


# ============================================================
# FUNCIONES MATEMÁTICAS (movidas aquí desde app.py)
# ============================================================

def disRSSI(rssi, A, n):
    """Convierte RSSI a distancia en metros usando el modelo log-distance path loss."""
    return 10 ** ((A - rssi) / (10 * n))


def coordTriangulo(a, b, c):
    """
    Calcula (x,y) usando la ley de cosenos dado un triángulo con lados a, b, c.
    """
    if (a + b > c) and (a + c > b) and (b + c > a):
        beta = math.acos((b**2 + c**2 - a**2) / (2 * b * c))
        x = c * math.cos(beta)
        y = c * math.sin(beta)
    else:
        # Triángulo degenerado — reparte la diferencia
        diff = b - (a + c)
        x = c + diff / 2
        y = 0
    return x, y


def triangulos(d, nodos):
    """
    Estima posición (x,y) usando el método de triángulos.
    d = [distancia_a_nodo0, distancia_a_nodo1, distancia_a_nodo2]
    nodos = lista de dicts con pos_x, pos_y de cada ESP32
    """
    # E1 está en el eje X, E2 en el eje Y (como el original)
    # Usamos las posiciones reales de los nodos desde la BD
    e1_x = nodos[1]['pos_x']
    e2_y = nodos[2]['pos_y']

    x1, y1 = coordTriangulo(d[1], e1_x, d[0])
    y2, x2 = coordTriangulo(d[2], e2_y, d[0])

    if y1 == 0 or x2 == 0:
        return x1, y2
    return (x1 + x2) / 2, (y1 + y2) / 2


def coordEjeCirculos(r1, r2, eje):
    """Intersección de círculos en un eje (trilateración simplificada)."""
    return -(r2**2 - r1**2 - eje**2) / (2 * eje)


def circulos(d, nodos):
    """
    Estima posición (x,y) usando el método de círculos (trilateración).
    """
    e1_x = nodos[1]['pos_x']
    e2_y = nodos[2]['pos_y']

    xc = coordEjeCirculos(d[0], d[1], e1_x)
    yc = coordEjeCirculos(d[0], d[2], e2_y)
    return (xc, yc)


def distancia(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)


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
                    'triang': [],
                    'circulos': [],
                }

    def get(self, area_id):
        with self._lock:
            return self._data.get(area_id, None)

    def clear(self, area_id):
        with self._lock:
            if area_id in self._data:
                d = self._data[area_id]
                for t in d['rssi']:
                    d['rssi'][t].clear()
                d['triang'].clear()
                d['circulos'].clear()

    def clear_all(self):
        with self._lock:
            self._data.clear()


# ============================================================
# MANAGER MQTT DINÁMICO
# ============================================================

class MQTTManager:
    """
    Maneja el cliente MQTT y las suscripciones dinámicas.
    Se crea una sola vez (cached por Streamlit).
    """

    def __init__(self):
        self.client = None
        self.active_area = None
        self.active_topics = []
        self.nodos_config = []  # Lista de dicts con info de cada ESP32
        self.store = AreaDataStore()
        self.connected = False

    def _ensure_client(self):
        """Crea el cliente MQTT si no existe."""
        if self.client is not None:
            return

        broker = db.get_config("mqtt_broker", "192.168.2.2")
        port = int(db.get_config("mqtt_port", "1883"))
        user = db.get_config("mqtt_user", "user")
        password = db.get_config("mqtt_password", "password")

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.username_pw_set(user, password)
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        try:
            self.client.connect(broker, port, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"[MQTT] Error conectando: {e}")
            self.connected = False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = True
        print(f"[MQTT] Conectado al broker (code={reason_code})")
        # Re-suscribir a topics activos si los hay
        if self.active_topics:
            for t in self.active_topics:
                client.subscribe(t)
            print(f"[MQTT] Re-suscrito a {len(self.active_topics)} topics")

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False
        print("[MQTT] Desconectado del broker")

    def _on_message(self, client, userdata, msg):
        """Callback que procesa cada lectura RSSI entrante."""
        try:
            topic = msg.topic
            rssi = int(msg.payload)

            if not (-100 < rssi < 0):
                return
            if self.active_area is None:
                return

            area_data = self.store.get(self.active_area)
            if area_data is None or topic not in area_data['rssi']:
                return

            n_muestras = int(db.get_config("n_muestras", "10"))

            # Acumular muestra
            if len(area_data['rssi'][topic]) < n_muestras:
                area_data['rssi'][topic].append(rssi)

            # ¿Ya tenemos suficientes muestras en todos los nodos?
            if all(len(area_data['rssi'][t]) >= n_muestras for t in self.active_topics):
                self._calcular_posicion(area_data, n_muestras)

        except Exception as e:
            print(f"[MQTT] Error procesando mensaje: {e}")

    def _calcular_posicion(self, area_data, n_muestras):
        """Calcula la posición estimada cuando hay suficientes muestras."""
        n_pathloss = float(db.get_config("n_pathloss", "3.223"))

        promedio = []
        for i, t in enumerate(self.active_topics):
            avg = sum(area_data['rssi'][t]) / n_muestras
            d = disRSSI(avg, self.nodos_config[i]['rssi_1m'], n_pathloss)
            promedio.append(d)
            area_data['rssi'][t].clear()

        area_data['triang'].append(triangulos(promedio, self.nodos_config))
        area_data['circulos'].append(circulos(promedio, self.nodos_config))
        print(f"[MQTT] Posición calculada: triang={area_data['triang'][-1]}, circulos={area_data['circulos'][-1]}")

    def seleccionar_area(self, area_id):
        """
        Cambia el área activa: desuscribe viejos topics, lee nodos de la BD,
        suscribe nuevos topics.
        """
        self._ensure_client()

        # Desuscribir topics anteriores
        if self.client and self.active_topics:
            for t in self.active_topics:
                self.client.unsubscribe(t)
            print(f"[MQTT] Desuscrito de {len(self.active_topics)} topics anteriores")

        # Leer nodos del área nueva
        nodos = db.listar_esp32_por_area(area_id)
        if len(nodos) < 3:
            print(f"[MQTT] Área {area_id} tiene solo {len(nodos)} nodos (necesita 3)")
            self.active_area = area_id
            self.active_topics = []
            self.nodos_config = []
            return False, f"El área tiene solo {len(nodos)} ESP32 (necesita 3)"

        self.active_area = area_id
        self.active_topics = [n['topic'] for n in nodos]
        self.nodos_config = nodos

        # Inicializar store del área
        self.store.init_area(area_id, self.active_topics)

        # Suscribir nuevos topics
        if self.client and self.connected:
            for t in self.active_topics:
                self.client.subscribe(t)
            print(f"[MQTT] Suscrito a {len(self.active_topics)} topics: {self.active_topics}")

        return True, None

    def get_estado(self):
        """Retorna el estado actual del manager para mostrar en la UI."""
        return {
            'connected': self.connected,
            'active_area': self.active_area,
            'active_topics': self.active_topics,
            'nodos': self.nodos_config,
        }


# Singleton cached por Streamlit
_manager_instance = None

def get_manager():
    """Devuelve la instancia única del MQTTManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = MQTTManager()
    return _manager_instance
