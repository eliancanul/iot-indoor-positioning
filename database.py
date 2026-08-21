"""
database.py — Capa de datos del Sistema de Posicionamiento IoT
Maneja todas las operaciones CRUD sobre SQLite.
Reemplaza los hardcodes del original por datos persistentes.
"""

import sqlite3
import os
import json
import statistics
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iot_platform.db")


def get_connection():
    """Devuelve una conexión nueva a la BD. SQLite maneja su propio pool."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Acceso por nombre de columna
    conn.execute("PRAGMA busy_timeout = 20000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """
    Crea las tablas si no existen y carga valores por defecto.
    Es idempotente — puede llamarse cada vez que arranca la app sin romper nada.
    """
    conn = get_connection()
    c = conn.cursor()

    # Tabla de áreas (cada área = un espacio físico con su propio plano)
    c.execute("""
        CREATE TABLE IF NOT EXISTS areas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT NOT NULL,
            ancho       REAL NOT NULL,
            alto        REAL NOT NULL,
            punto_real_x REAL DEFAULT 2.0,
            punto_real_y REAL DEFAULT 2.0,
            creado_en   TEXT DEFAULT (datetime('now','localtime'))

        )
    """)

    # Tabla de nodos ESP32
    c.execute("""
        CREATE TABLE IF NOT EXISTS esp32 (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id     TEXT NOT NULL UNIQUE,
            topic       TEXT NOT NULL UNIQUE,
            pos_x       REAL NOT NULL,
            pos_y       REAL NOT NULL,
            rssi_1m     REAL NOT NULL,
            n_pathloss REAL,
            area_id     INTEGER NOT NULL,
            creado_en   TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE RESTRICT
        )
    """)

    # Migración aditiva: calibración de propagación individual por nodo.
    esp_columns = {row[1] for row in c.execute("PRAGMA table_info(esp32)").fetchall()}
    if "n_pathloss" not in esp_columns:
        c.execute("ALTER TABLE esp32 ADD COLUMN n_pathloss REAL")

    # Tabla de configuración global (clave-valor)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config_global (
            clave   TEXT PRIMARY KEY,
            valor   TEXT
        )
    """)

    # Tabla del dataset para el machine learning
    c.execute("""
CREATE TABLE IF NOT EXISTS dataset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now','localtime')),
    area_id INTEGER NOT NULL,
    experimento INTEGER DEFAULT 1,
    muestra INTEGER,

    rssi_1 REAL,
    rssi_2 REAL,
    rssi_3 REAL,

    dist_1 REAL,
    dist_2 REAL,
    dist_3 REAL,

    x_real REAL,
    y_real REAL,

    x_tri REAL,
    y_tri REAL,
    error_tri REAL,

    x_circ REAL,
    y_circ REAL,
    error_circ REAL,

    pathloss REAL,
    muestras_rssi INTEGER,

    esp0_x REAL,
    esp0_y REAL,
    esp1_x REAL,
    esp1_y REAL,
    esp2_x REAL,
    esp2_y REAL,

    FOREIGN KEY(area_id) REFERENCES areas(id)
)
""")

    # Compatibilidad con consultas/exportadores que usan estos nombres.
    # x_tri/y_tri siguen siendo las columnas canónicas.
    dataset_columns = {row[1] for row in c.execute("PRAGMA table_info(dataset)").fetchall()}
    if "trian_x" not in dataset_columns:
        c.execute("ALTER TABLE dataset ADD COLUMN trian_x REAL")
    if "triang_y" not in dataset_columns:
        c.execute("ALTER TABLE dataset ADD COLUMN triang_y REAL")
    c.execute("UPDATE dataset SET trian_x = x_tri WHERE trian_x IS NULL AND x_tri IS NOT NULL")
    c.execute("UPDATE dataset SET triang_y = y_tri WHERE triang_y IS NULL AND y_tri IS NOT NULL")


    # ============================================================
    # ESQUEMA NORMALIZADO PARA RECOLECCIÓN Y ML
    # ============================================================
    c.execute("""
        CREATE TABLE IF NOT EXISTS dataset_cycle_dedup (
            cycle_signature TEXT PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS capture_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            condiciones_ambientales TEXT NOT NULL,
            orden_posiciones_json TEXT NOT NULL,
            protocol_version TEXT NOT NULL DEFAULT 'capture-v1',
            started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            finished_at TEXT,
            UNIQUE(area_id, codigo),
            FOREIGN KEY(area_id) REFERENCES areas(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS collection_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area_id INTEGER NOT NULL,
            campaign_id INTEGER,
            started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            finished_at TEXT,
            beacon_id TEXT,
            environment_tag TEXT,
            orientation TEXT,
            layout_version TEXT,
            independence_evidence TEXT,
            obstacle_description TEXT,
            obstacle_photo_ref TEXT,
            operator_notes TEXT,
            node_schema_hash TEXT NOT NULL,
            FOREIGN KEY(area_id) REFERENCES areas(id),
            FOREIGN KEY(campaign_id) REFERENCES capture_campaigns(id)
        )
    """)

    # Migración aditiva para instalaciones que ya tenían collection_sessions.
    # Las columnas históricas permanecen intactas y las nuevas admiten NULL para
    # que las sesiones antiguas sigan siendo auditables sin inventar metadatos.
    session_columns = {
        row[1] for row in c.execute("PRAGMA table_info(collection_sessions)").fetchall()
    }
    session_migrations = {
        "campaign_id": "INTEGER",
        "orientation": "TEXT",
        "layout_version": "TEXT",
        "independence_evidence": "TEXT",
        "obstacle_description": "TEXT",
        "obstacle_photo_ref": "TEXT",
    }
    for column, definition in session_migrations.items():
        if column not in session_columns:
            c.execute(
                f"ALTER TABLE collection_sessions ADD COLUMN {column} {definition}"
            )

    c.execute("""
        CREATE TABLE IF NOT EXISTS fingerprint_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            area_id INTEGER NOT NULL,
            captured_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            cycle_number INTEGER NOT NULL,
            x_real REAL NOT NULL,
            y_real REAL NOT NULL,
            quality_status TEXT NOT NULL DEFAULT 'eligible',
            quality_reasons_json TEXT NOT NULL DEFAULT '[]',
            x_tri REAL,
            y_tri REAL,
            x_circ REAL,
            y_circ REAL,
            FOREIGN KEY(session_id) REFERENCES collection_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY(area_id) REFERENCES areas(id)
        )
    """)

    fingerprint_columns = {
        row[1] for row in c.execute("PRAGMA table_info(fingerprint_samples)").fetchall()
    }
    if "trian_x" not in fingerprint_columns:
        c.execute("ALTER TABLE fingerprint_samples ADD COLUMN trian_x REAL")
    if "triang_y" not in fingerprint_columns:
        c.execute("ALTER TABLE fingerprint_samples ADD COLUMN triang_y REAL")
    c.execute("UPDATE fingerprint_samples SET trian_x = x_tri WHERE trian_x IS NULL AND x_tri IS NOT NULL")
    c.execute("UPDATE fingerprint_samples SET triang_y = y_tri WHERE triang_y IS NULL AND y_tri IS NOT NULL")

    # La ventana temporal forma parte de la evidencia de calidad. Las columnas
    # nuevas son aditivas; las muestras históricas sin timestamps por lectura
    # conservan NULL en lugar de recibir tiempos inventados.
    timing_columns = {
        row[1] for row in c.execute("PRAGMA table_info(fingerprint_samples)").fetchall()
    }
    for column, definition in {
        "quality_status": "TEXT NOT NULL DEFAULT 'eligible'",
        "quality_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
        "window_start_at": "TEXT",
        "window_end_at": "TEXT",
        "window_skew_s": "REAL",
    }.items():
        if column not in timing_columns:
            c.execute(
                f"ALTER TABLE fingerprint_samples ADD COLUMN {column} {definition}"
            )

    c.execute("""
        CREATE TABLE IF NOT EXISTS fingerprint_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id INTEGER NOT NULL,
            node_id TEXT NOT NULL,
            rssi_median REAL,
            rssi_iqr REAL,
            rssi_std REAL,
            rssi_min REAL,
            rssi_max REAL,
            reading_count INTEGER NOT NULL DEFAULT 0,
            raw_values_json TEXT,
            present INTEGER NOT NULL DEFAULT 1,
            UNIQUE(sample_id, node_id),
            FOREIGN KEY(sample_id) REFERENCES fingerprint_samples(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS model_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area_id INTEGER NOT NULL,
            algorithm TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            feature_schema_hash TEXT NOT NULL,
            dataset_hash TEXT NOT NULL,
            training_sessions_json TEXT NOT NULL DEFAULT '[]',
            metrics_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            is_active INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(area_id) REFERENCES areas(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS position_estimate_diagnostics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT,
            raw_x REAL,
            raw_y REAL,
            residual_m REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(sample_id) REFERENCES fingerprint_samples(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS position_estimates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            x_estimated REAL NOT NULL,
            y_estimated REAL NOT NULL,
            error_m REAL,
            confidence REAL,
            model_id INTEGER,
            latency_ms REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(sample_id) REFERENCES fingerprint_samples(id) ON DELETE CASCADE,
            FOREIGN KEY(model_id) REFERENCES model_registry(id)
        )
    """)

    # Configuración por defecto (solo si no existe ya)
    defaults = {
        "n_pathloss": "3.223",
        "n_muestras": "10",
        # Política mínima de estabilidad: permite ruido moderado sin aceptar
        # ventanas completamente erráticas.
        "max_iqr_db": "10",
        "max_std_db": "6",
        # Los ESP32 publican de forma asíncrona; 20 s cubre una ventana completa
        # sin aceptar un ciclo que quedó abandonado durante minutos.
        "max_window_skew_s": "20",
        # Una trilateración con error superior a este valor no entra al dataset.
        # El resultado de círculos se conserva como comparativa independiente.
        "max_error_triangulos": "2.0",
        # Las capturas nuevas necesitan contexto físico explícito. El valor se
        # puede desactivar solo como adaptador temporal para instalaciones
        # históricas que todavía no migraron su protocolo de captura.
        "capture_context_required": "1",
        "mqtt_broker": "192.168.2.2",
        "mqtt_port": "1883",
        # Las credenciales deben configurarse localmente desde Settings.
        "mqtt_user": "",
        "mqtt_password": "",
    }
    for clave, valor in defaults.items():
        c.execute(
            "INSERT OR IGNORE INTO config_global (clave, valor) VALUES (?, ?)",
            (clave, valor),
        )

    conn.commit()
    conn.close()


# ============================================================
# CRUD — ÁREAS
# ============================================================

def crear_area(nombre, ancho, alto, punto_real_x=2.0, punto_real_y=2.0):
    """
    Crea un área nueva.
    Retorna (True, id) si ok, (False, mensaje_error) si falla.
    """
    try:
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            """INSERT INTO areas (nombre, ancho, alto, punto_real_x, punto_real_y)
               VALUES (?, ?, ?, ?, ?)""",
            (nombre.strip(), float(ancho), float(alto), float(punto_real_x), float(punto_real_y)),
        )
        conn.commit()
        area_id = c.lastrowid
        conn.close()
        return True, area_id
    except Exception as e:
        return False, str(e)


def listar_areas():
    """Retorna lista de diccionarios con todas las áreas."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM areas ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_area(area_id):
    """Retorna un diccionario con el área pedida, o None."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM areas WHERE id = ?", (area_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def actualizar_area(area_id, nombre, ancho, alto, punto_real_x=None, punto_real_y=None):
    """Actualiza un área existente."""
    conn = get_connection()
    c = conn.cursor()

    if punto_real_x is not None and punto_real_y is not None:
        c.execute(
            """UPDATE areas
               SET nombre = ?, ancho = ?, alto = ?, punto_real_x = ?, punto_real_y = ?
               WHERE id = ?""",
            (nombre.strip(), float(ancho), float(alto),
             float(punto_real_x), float(punto_real_y), area_id),
        )
    else:
        c.execute(
            "UPDATE areas SET nombre = ?, ancho = ?, alto = ? WHERE id = ?",
            (nombre.strip(), float(ancho), float(alto), area_id),
        )
    conn.commit()
    conn.close()


def eliminar_area(area_id):
    """
    Elimina un área.
    VALIDACIÓN: no se puede eliminar si tiene ESP32 asignados.
    Retorna (True, None) si ok, (False, mensaje) si bloqueado.
    """
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM esp32 WHERE area_id = ?", (area_id,)
    ).fetchone()[0]

    if count > 0:
        conn.close()
        return False, f"No se puede eliminar: el área tiene {count} ESP32 asignados. Elimina los nodos primero."

    conn.execute("DELETE FROM areas WHERE id = ?", (area_id,))
    conn.commit()
    conn.close()
    return True, None


# ============================================================
# CRUD — ESP32
# ============================================================

MAX_NODOS_POR_AREA = 3


def crear_esp32(node_id, topic, pos_x, pos_y, rssi_1m, area_id):
    """
    Registra un ESP32 nuevo.
    Validaciones:
      - node_id único
      - topic único
      - máximo 3 ESP32 por área
    Retorna (True, id) o (False, mensaje).
    """
    conn = get_connection()
    c = conn.cursor()

    # Validar máximo 3 por área
    count = c.execute(
        "SELECT COUNT(*) FROM esp32 WHERE area_id = ?", (area_id,)
    ).fetchone()[0]
    if count >= MAX_NODOS_POR_AREA:
        conn.close()
        return False, f"El área ya tiene el máximo de {MAX_NODOS_POR_AREA} ESP32."

    # Validar node_id único
    exists_node = c.execute(
        "SELECT COUNT(*) FROM esp32 WHERE node_id = ?", (node_id.strip(),)
    ).fetchone()[0]
    if exists_node:
        conn.close()
        return False, f"Ya existe un ESP32 con node_id '{node_id}'."

    # Validar topic único
    exists_topic = c.execute(
        "SELECT COUNT(*) FROM esp32 WHERE topic = ?", (topic.strip(),)
    ).fetchone()[0]
    if exists_topic:
        conn.close()
        return False, f"Ya existe un ESP32 con topic '{topic}'."

    try:
        c.execute(
            """INSERT INTO esp32 (node_id, topic, pos_x, pos_y, rssi_1m, area_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (node_id.strip(), topic.strip(), float(pos_x), float(pos_y),
             float(rssi_1m), area_id),
        )
        conn.commit()
        esp_id = c.lastrowid
        conn.close()
        return True, esp_id
    except Exception as e:
        conn.close()
        return False, str(e)


def listar_esp32():
    """Retorna todos los ESP32 registrados."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM esp32 ORDER BY area_id, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def listar_esp32_por_area(area_id):
    """Retorna los ESP32 asignados a un área específica (ordenados por id)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM esp32 WHERE area_id = ? ORDER BY id", (area_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_esp32(esp_id):
    """Retorna un diccionario con el ESP32 pedido, o None."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM esp32 WHERE id = ?", (esp_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def actualizar_esp32(esp_id, node_id, topic, pos_x, pos_y, rssi_1m, area_id):
    """Actualiza un ESP32 existente."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """UPDATE esp32
           SET node_id = ?, topic = ?, pos_x = ?, pos_y = ?, rssi_1m = ?, area_id = ?
           WHERE id = ?""",
        (node_id.strip(), topic.strip(), float(pos_x), float(pos_y),
         float(rssi_1m), area_id, esp_id),
    )
    conn.commit()
    conn.close()


def actualizar_calibracion_nodo(esp_id, rssi_1m=None, n_pathloss=None):
    """Actualiza solo parámetros calibrados de un ESP32; conserva geometría/topics."""
    if rssi_1m is None and n_pathloss is None:
        return
    conn = get_connection()
    sets, values = [], []
    if rssi_1m is not None:
        sets.append("rssi_1m = ?")
        values.append(float(rssi_1m))
    if n_pathloss is not None:
        if not 1.0 <= float(n_pathloss) <= 10.0:
            conn.close()
            raise ValueError("n_pathloss debe estar entre 1.0 y 10.0")
        sets.append("n_pathloss = ?")
        values.append(float(n_pathloss))
    values.append(esp_id)
    conn.execute(f"UPDATE esp32 SET {', '.join(sets)} WHERE id = ?", values)
    conn.commit()
    conn.close()


def eliminar_esp32(esp_id):
    """Elimina un ESP32 por id."""
    conn = get_connection()
    conn.execute("DELETE FROM esp32 WHERE id = ?", (esp_id,))
    conn.commit()
    conn.close()


# ============================================================
# CONFIG GLOBAL
# ============================================================

def listar_topics_con_area():
    """
    JOIN esp32 ↔ areas: devuelve lista de dicts con info completa de cada nodo
    incluyendo datos del área a la que pertenece.
    Útil para suscribirse masivamente o mostrar tablas combinadas.

    Cada dict: {id, node_id, topic, pos_x, pos_y, rssi_1m, area_id,
                area_nombre, area_ancho, area_alto}
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT e.id, e.node_id, e.topic, e.pos_x, e.pos_y, e.rssi_1m,
               e.area_id, a.nombre AS area_nombre,
               a.ancho AS area_ancho, a.alto AS area_alto
        FROM esp32 e
        JOIN areas a ON e.area_id = a.id
        ORDER BY e.area_id, e.id
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_config(clave, default=None):
    """Lee un valor de config_global. Retorna como string."""
    conn = get_connection()
    row = conn.execute(
        "SELECT valor FROM config_global WHERE clave = ?", (clave,)
    ).fetchone()
    conn.close()
    return row[0] if row else default


def get_all_config():
    """Retorna un diccionario con toda la config global."""
    conn = get_connection()
    rows = conn.execute("SELECT clave, valor FROM config_global").fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


def set_config(clave, valor):
    """Inserta o actualiza un valor de config_global (UPSERT)."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO config_global (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor = ?",
        (clave, str(valor), str(valor)),
    )
    conn.commit()
    conn.close()


# ============================================================
# DATOS SEMILLA (opcional — para testing inicial)
# ============================================================

def cargar_datos_semilla():
    """
    Crea un área de ejemplo con 3 ESP32 (réplica del original hardcodeado).
    Solo si no hay áreas todavía.
    """
    if listar_areas():
        return  # Ya hay datos

    ok, area_id = crear_area(
        nombre="Área Laboratorio",
        ancho=8.0,
        alto=6.0,
        punto_real_x=2.0,
        punto_real_y=2.0,
    )
    if not ok:
        return

    nodos = [
        ("ESP32_0", "RSSI_0", 0.0, 0.0, -62.5),
        ("ESP32_1", "RSSI_1", 4.0, 0.0, -69.93),
        ("ESP32_2", "RSSI_2", 0.0, 3.0, -65.08),
    ]
    for node_id, topic, x, y, rssi in nodos:
        crear_esp32(node_id, topic, x, y, rssi, area_id)

def obtener_posicion_beacon(area_id):
    """Retorna (x, y) del punto real configurado para el área, o None."""
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT punto_real_x, punto_real_y
        FROM areas
        WHERE id=?
    """, (area_id,))
    fila = c.fetchone()
    conn.close()
    if fila:
        return fila["punto_real_x"], fila["punto_real_y"]
    return None

CAPTURE_ORIENTATIONS = {"north", "east", "south", "west", "unknown"}


def _normalizar_orden_posiciones(orden_posiciones):
    if not orden_posiciones:
        raise ValueError("La campaña requiere un orden de posiciones")
    normalized = []
    seen = set()
    for position in orden_posiciones:
        if not isinstance(position, (list, tuple)) or len(position) != 2:
            raise ValueError("Cada posición debe tener coordenadas x,y")
        try:
            point = [float(position[0]), float(position[1])]
        except (TypeError, ValueError) as exc:
            raise ValueError("Las coordenadas de posición deben ser numéricas") from exc
        key = tuple(point)
        if key in seen:
            raise ValueError("El orden de posiciones no puede contener duplicados")
        seen.add(key)
        normalized.append(point)
    return normalized


def crear_campana(area_id, codigo, descripcion, condiciones_ambientales,
                  orden_posiciones, protocol_version="capture-v1"):
    """Crea una campaña física con protocolo y recorrido reproducibles."""
    codigo = str(codigo or "").strip()
    descripcion = str(descripcion or "").strip()
    condiciones_ambientales = str(condiciones_ambientales or "").strip()
    protocol_version = str(protocol_version or "").strip()
    if not codigo or not descripcion or not condiciones_ambientales or not protocol_version:
        raise ValueError("Código, descripción, entorno y protocolo son obligatorios")
    positions = _normalizar_orden_posiciones(orden_posiciones)

    conn = get_connection()
    try:
        cur = conn.execute(
            """INSERT INTO capture_campaigns(
                   area_id, codigo, descripcion, condiciones_ambientales,
                   orden_posiciones_json, protocol_version)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (area_id, codigo, descripcion, condiciones_ambientales,
             json.dumps(positions, separators=(",", ":"), ensure_ascii=False),
             protocol_version),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError(f"No se pudo crear la campaña: {exc}") from exc
    finally:
        conn.close()


def listar_campanas(area_id=None):
    """Lista campañas físicas, opcionalmente filtradas por área."""
    conn = get_connection()
    if area_id is None:
        rows = conn.execute(
            "SELECT * FROM capture_campaigns ORDER BY id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM capture_campaigns WHERE area_id=? ORDER BY id",
            (area_id,),
        ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def obtener_posiciones_campana(campaign_id):
    """Devuelve el recorrido fijo de una campaña como listas ``[x, y]``."""
    conn = get_connection()
    row = conn.execute(
        "SELECT orden_posiciones_json FROM capture_campaigns WHERE id=?",
        (campaign_id,),
    ).fetchone()
    conn.close()
    if row is None:
        raise ValueError("La campaña no existe")
    try:
        positions = json.loads(row["orden_posiciones_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("La campaña tiene un orden de posiciones inválido") from exc
    return _normalizar_orden_posiciones(positions)


def listar_sesiones_captura(area_id, campaign_id=None, solo_abiertas=True):
    """Lista sesiones normalizadas para reanudar una sesión física existente."""
    conn = get_connection()
    clauses = ["area_id = ?"]
    values = [area_id]
    if campaign_id is not None:
        clauses.append("campaign_id = ?")
        values.append(campaign_id)
    if solo_abiertas:
        clauses.append("finished_at IS NULL")
    rows = conn.execute(
        "SELECT * FROM collection_sessions WHERE " + " AND ".join(clauses) + " ORDER BY id",
        values,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def obtener_sesion_captura(session_id):
    """Devuelve el contexto de una sesión por id, o ``None`` si no existe."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM collection_sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def crear_sesion_captura(campaign_id, area_id, orientation, environment_tag,
                         layout_version, independence_evidence,
                         obstacle_description=None, obstacle_photo_ref=None,
                         beacon_id=None, operator_notes=None,
                         node_schema_hash=""):
    """Abre una sesión física con el contexto mínimo auditable.

    Esta es la interfaz estricta para capturas nuevas. ``crear_sesion`` se
    mantiene como adaptador de compatibilidad para sesiones históricas.
    """
    orientation = str(orientation or "").strip().lower()
    environment_tag = str(environment_tag or "").strip()
    layout_version = str(layout_version or "").strip()
    independence_evidence = str(independence_evidence or "").strip()
    obstacle_description = str(obstacle_description or "").strip()
    obstacle_photo_ref = str(obstacle_photo_ref or "").strip()
    if orientation not in CAPTURE_ORIENTATIONS:
        raise ValueError("orientation debe ser north, east, south, west o unknown")
    if not environment_tag or not layout_version or not independence_evidence:
        raise ValueError("Faltan metadatos obligatorios de la sesión")
    if not obstacle_description and not obstacle_photo_ref:
        raise ValueError("Se requiere descripción o referencia de fotografía de obstáculos")

    conn = get_connection()
    try:
        campaign = conn.execute(
            "SELECT area_id FROM capture_campaigns WHERE id=?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            raise ValueError("La campaña no existe")
        if campaign["area_id"] != area_id:
            raise ValueError("La campaña no pertenece al área indicada")
        cur = conn.execute(
            """INSERT INTO collection_sessions(
                   area_id, campaign_id, beacon_id, environment_tag,
                   orientation, layout_version, independence_evidence,
                   obstacle_description, obstacle_photo_ref,
                   operator_notes, node_schema_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (area_id, campaign_id, beacon_id, environment_tag, orientation,
             layout_version, independence_evidence, obstacle_description,
             obstacle_photo_ref, operator_notes, node_schema_hash),
        )
        conn.commit()
        return cur.lastrowid
    except ValueError:
        conn.rollback()
        raise
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ValueError(f"No se pudo crear la sesión: {exc}") from exc
    finally:
        conn.close()


def guardar_dataset(
    area_id,
    experimento,
    muestra,
    rssi,
    dist,
    punto_real,
    triangulos,
    circulos,
    pathloss,
    muestras_rssi,
    nodos
):
    conn=get_connection()
    c=conn.cursor()

    c.execute("""
    INSERT INTO dataset(
    area_id,experimento,muestra,
    rssi_1,rssi_2,rssi_3,
    dist_1,dist_2,dist_3,
    x_real,y_real,
    x_tri,y_tri,trian_x,triang_y,error_tri,
    x_circ,y_circ,error_circ,
    pathloss,muestras_rssi,
    esp0_x,esp0_y,
    esp1_x,esp1_y,
    esp2_x,esp2_y)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,(
        area_id,experimento,muestra,
        rssi[0],rssi[1],rssi[2],
        dist[0],dist[1],dist[2],
        punto_real[0],punto_real[1],
        triangulos["x"],triangulos["y"],triangulos["x"],triangulos["y"],triangulos["error"],
        circulos["x"],circulos["y"],circulos["error"],
        pathloss,muestras_rssi,
        nodos[0]["pos_x"],nodos[0]["pos_y"],
        nodos[1]["pos_x"],nodos[1]["pos_y"],
        nodos[2]["pos_x"],nodos[2]["pos_y"],
    ))
    conn.commit()
    rid=c.lastrowid
    conn.close()
    return rid



def crear_sesion(area_id, beacon_id=None, environment_tag=None,
                 operator_notes=None, node_schema_hash=''):
    """Crea una sesión física de recolección y devuelve su id."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO collection_sessions
           (area_id, beacon_id, environment_tag, operator_notes, node_schema_hash)
           VALUES (?, ?, ?, ?, ?)""",
        (area_id, beacon_id, environment_tag, operator_notes, node_schema_hash),
    )
    conn.commit()
    session_id = cur.lastrowid
    conn.close()
    return session_id


def cerrar_sesion(session_id):
    """Marca una sesión como terminada."""
    conn = get_connection()
    conn.execute(
        "UPDATE collection_sessions SET finished_at = datetime('now','localtime') WHERE id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def crear_muestra_fingerprint(session_id, area_id, cycle_number,
                              x_real, y_real, x_tri=None, y_tri=None,
                              x_circ=None, y_circ=None):
    """Crea una muestra etiquetada y devuelve su id."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO fingerprint_samples
           (session_id, area_id, cycle_number, x_real, y_real,
            x_tri, y_tri, trian_x, triang_y, x_circ, y_circ)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, area_id, cycle_number, x_real, y_real,
         x_tri, y_tri, x_tri, y_tri, x_circ, y_circ),
    )
    conn.commit()
    sample_id = cur.lastrowid
    conn.close()
    return sample_id


def guardar_lectura_fingerprint(sample_id, node_id, rssi_median=None,
                                rssi_iqr=None, rssi_std=None, rssi_min=None,
                                rssi_max=None, reading_count=0,
                                raw_values=None, present=True):
    """Guarda o actualiza las estadísticas RSSI de un nodo en una muestra."""
    import json
    raw_json = json.dumps(raw_values if raw_values is not None else [], separators=(',', ':'))
    conn = get_connection()
    conn.execute(
        """INSERT INTO fingerprint_readings
           (sample_id, node_id, rssi_median, rssi_iqr, rssi_std,
            rssi_min, rssi_max, reading_count, raw_values_json, present)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sample_id, node_id) DO UPDATE SET
             rssi_median=excluded.rssi_median,
             rssi_iqr=excluded.rssi_iqr,
             rssi_std=excluded.rssi_std,
             rssi_min=excluded.rssi_min,
             rssi_max=excluded.rssi_max,
             reading_count=excluded.reading_count,
             raw_values_json=excluded.raw_values_json,
             present=excluded.present""",
        (sample_id, node_id, rssi_median, rssi_iqr, rssi_std,
         rssi_min, rssi_max, reading_count, raw_json, int(bool(present))),
    )
    conn.commit()
    conn.close()


def registrar_modelo(area_id, algorithm, artifact_path, feature_schema_hash,
                     dataset_hash, training_sessions=None, metrics=None,
                     is_active=False):
    """Registra un artefacto de ML y devuelve su id."""
    import json
    conn = get_connection()
    if is_active:
        conn.execute("UPDATE model_registry SET is_active = 0 WHERE area_id = ?", (area_id,))
    cur = conn.execute(
        """INSERT INTO model_registry
           (area_id, algorithm, artifact_path, feature_schema_hash,
            dataset_hash, training_sessions_json, metrics_json, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (area_id, algorithm, artifact_path, feature_schema_hash, dataset_hash,
         json.dumps(training_sessions or [], separators=(',', ':')),
         json.dumps(metrics or {}, sort_keys=True, separators=(',', ':')),
         int(bool(is_active))),
    )
    conn.commit()
    model_id = cur.lastrowid
    conn.close()
    return model_id


def guardar_estimacion(sample_id, method, x_estimated, y_estimated,
                       error_m=None, confidence=None, model_id=None,
                       latency_ms=None):
    """Guarda una predicción comparable de cualquier método."""
    conn = get_connection()
    cur = conn.execute(
        """INSERT INTO position_estimates
           (sample_id, method, x_estimated, y_estimated, error_m,
            confidence, model_id, latency_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (sample_id, method, x_estimated, y_estimated, error_m,
         confidence, model_id, latency_ms),
    )
    conn.commit()
    estimate_id = cur.lastrowid
    conn.close()
    return estimate_id



def claim_cycle_signature(signature):
    """Reclama una firma de ciclo de forma atómica; False si ya existía."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT OR IGNORE INTO dataset_cycle_dedup (cycle_signature) VALUES (?)",
        (str(signature),),
    )
    conn.commit()
    claimed = cur.rowcount == 1
    conn.close()
    return claimed



def _format_window_timestamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value)).isoformat(timespec="milliseconds")
    return str(value) if value is not None else None


def guardar_ciclo_captura(area_id, session_id, cycle_id, x_real, y_real,
                          readings, estimates, max_window_skew_s=2.0,
                          invalid_estimates=None, max_error_triangulos=None,
                          quality_status="eligible", quality_reasons=None):
    """Guarda una muestra normalizada completa en una transacción o no guarda nada.

    La capa de persistencia también protege la regla de calidad: una estimación
    triangular cuyo error individual supere el umbral no se inserta. La
    estimación de círculos se mantiene como comparativa independiente.
    """
    if not cycle_id:
        raise ValueError("cycle_id es obligatorio")
    quality_status = str(quality_status or "eligible").strip().lower()
    if quality_status not in {"eligible", "dirty"}:
        raise ValueError("quality_status debe ser eligible o dirty")
    quality_reasons = set(str(reason) for reason in (quality_reasons or []))
    timestamps = [
        timestamp
        for reading in readings
        for timestamp in (reading.get('window_start_at'), reading.get('captured_at'))
        if timestamp is not None
    ]
    window_skew_s = max(timestamps) - min(timestamps) if timestamps else None
    if window_skew_s is not None and window_skew_s > max_window_skew_s:
        quality_status = "dirty"
        quality_reasons.add("window_skew_exceeded")
    if quality_status == "dirty" and not quality_reasons:
        quality_reasons.add("quality_policy")
    if len(readings) != 3 or any(not r.get('node_id') or not r.get('rssi_values') for r in readings):
        return {'saved': False, 'reason': 'incomplete_readings'}
    if max_error_triangulos is None:
        try:
            max_error_triangulos = float(get_config('max_error_triangulos', '2.0'))
        except (TypeError, ValueError):
            max_error_triangulos = 2.0
    if max_error_triangulos < 0:
        max_error_triangulos = 2.0

    # Copia para no modificar el diccionario que conserva la capa MQTT/UI.
    estimates = dict(estimates or {})
    tri = estimates.get('triangulos')
    if tri is not None and x_real is not None and y_real is not None:
        tri_error = ((tri[0] - x_real) ** 2 + (tri[1] - y_real) ** 2) ** 0.5
        if tri_error > max_error_triangulos:
            estimates['triangulos'] = None
            invalid_estimates = list(invalid_estimates or [])
            if not any(item.get('method') == 'triangulos' and
                       item.get('reason') == 'high_error' for item in invalid_estimates):
                invalid_estimates.append({
                    'method': 'triangulos',
                    'reason': 'high_error',
                    'raw_x': tri[0],
                    'raw_y': tri[1],
                    'residual_m': tri_error,
                })

    conn = get_connection()
    try:
        if session_id is not None:
            session = conn.execute(
                "SELECT area_id, finished_at FROM collection_sessions WHERE id=?",
                (session_id,),
            ).fetchone()
            if session is None:
                raise ValueError("La sesión física no existe")
            if session["area_id"] != area_id:
                raise ValueError("La sesión física no pertenece al área indicada")
            if session["finished_at"] is not None:
                raise ValueError("La sesión física ya está cerrada")

        conn.execute('BEGIN IMMEDIATE')
        cur = conn.execute(
            "INSERT OR IGNORE INTO dataset_cycle_dedup (cycle_signature) VALUES (?)", (cycle_id,)
        )
        if cur.rowcount != 1:
            conn.rollback()
            return {'saved': False, 'reason': 'duplicate_cycle'}
        if session_id is None:
            nodes = [r['node_id'] for r in readings]
            cur = conn.execute(
                """INSERT INTO collection_sessions(area_id, environment_tag, node_schema_hash)
                   VALUES (?, ?, ?)""", (area_id, 'live', '|'.join(nodes))
            )
            session_id = cur.lastrowid
        cycle_number = conn.execute(
            "SELECT COUNT(*) + 1 FROM fingerprint_samples WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        tri = estimates.get('triangulos')
        circ = estimates.get('circulos')
        cur = conn.execute(
            """INSERT INTO fingerprint_samples(
                   session_id,area_id,cycle_number,x_real,y_real,
                   quality_status,quality_reasons_json,
                   window_start_at,window_end_at,window_skew_s,
                   x_tri,y_tri,trian_x,triang_y,x_circ,y_circ)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (session_id, area_id, cycle_number, x_real, y_real,
             quality_status, json.dumps(sorted(quality_reasons), separators=(",", ":")),
             _format_window_timestamp(min(timestamps)) if timestamps else None,
             _format_window_timestamp(max(timestamps)) if timestamps else None,
             window_skew_s,
             tri[0] if tri else None, tri[1] if tri else None,
             tri[0] if tri else None, tri[1] if tri else None,
             circ[0] if circ else None, circ[1] if circ else None),
        )
        sample_id = cur.lastrowid
        for reading in readings:
            values = reading['rssi_values']
            ordered = sorted(values)
            mean = sum(values) / len(values)
            q1, q3 = ordered[len(ordered)//4], ordered[(3*len(ordered))//4]
            conn.execute(
                """INSERT INTO fingerprint_readings(sample_id,node_id,rssi_median,rssi_iqr,rssi_std,rssi_min,rssi_max,reading_count,raw_values_json,present)
                   VALUES (?,?,?,?,?,?,?,?,?,1)""",
                (sample_id, reading['node_id'], statistics.median(values), q3-q1,
                 (sum((v-mean)**2 for v in values)/len(values))**0.5,
                 min(values), max(values), len(values), json.dumps(values, separators=(',', ':'))),
            )
        for invalid in invalid_estimates or []:
            conn.execute(
                """INSERT INTO position_estimate_diagnostics
                   (sample_id,method,status,reason,raw_x,raw_y,residual_m)
                   VALUES (?,?,?,?,?,?,?)""",
                (sample_id, invalid['method'], 'invalid', invalid.get('reason'),
                 invalid.get('raw_x'), invalid.get('raw_y'), invalid.get('residual_m')),
            )
        estimate_count = 0
        for method, estimate in estimates.items():
            if estimate is None:
                continue
            error = ((estimate[0]-x_real)**2 + (estimate[1]-y_real)**2)**0.5
            conn.execute(
                "INSERT INTO position_estimates(sample_id,method,x_estimated,y_estimated,error_m) VALUES (?,?,?,?,?)",
                (sample_id, method, estimate[0], estimate[1], error),
            )
            estimate_count += 1
        conn.commit()
        return {'saved': True, 'session_id': session_id, 'sample_id': sample_id,
                'reading_count': len(readings), 'estimate_count': estimate_count,
                'quality_status': quality_status,
                'quality_reasons': sorted(quality_reasons)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ============================================================
# TEST — ejecutar directamente para validar
# ============================================================

if __name__ == "__main__":
    init_db()
    cargar_datos_semilla()

    print("=== ÁREAS ===")
    for a in listar_areas():
        print(f"  [{a['id']}] {a['nombre']} ({a['ancho']}x{a['alto']}m) "
              f"real=({a['punto_real_x']},{a['punto_real_y']})")

    print("\n=== ESP32 ===")
    for e in listar_esp32():
        print(f"  [{e['id']}] {e['node_id']} → topic={e['topic']} "
              f"pos=({e['pos_x']},{e['pos_y']}) rssi_1m={e['rssi_1m']} "
              f"area_id={e['area_id']}")

    print("\n=== CONFIG ===")
    for k, v in get_all_config().items():
        print(f"  {k} = {v}")

    print("\n=== VALIDACIONES ===")
    # Intentar meter un 4to nodo al área 1 (debe fallar)
    ok, msg = crear_esp32("ESP32_3", "RSSI_3", 1.0, 1.0, -60.0, 1)
    print(f"  4to nodo en área 1: ok={ok} → {msg}")

    # Intentar duplicar node_id
    ok2, msg2 = crear_esp32("ESP32_0", "RSSI_9", 1.0, 1.0, -60.0, 1)
    print(f"  node_id duplicado: ok={ok2} → {msg2}")

    print("\nTODO_OK")
