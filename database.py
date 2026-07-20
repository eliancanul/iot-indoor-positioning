"""
database.py — Capa de datos del Sistema de Posicionamiento IoT
Maneja todas las operaciones CRUD sobre SQLite.
Reemplaza los hardcodes del original por datos persistentes.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "iot_platform.db")


def get_connection():
    """Devuelve una conexión nueva a la BD. SQLite maneja su propio pool."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Acceso por nombre de columna
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
            area_id     INTEGER NOT NULL,
            creado_en   TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE RESTRICT
        )
    """)

    # Tabla de configuración global (clave-valor)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config_global (
            clave   TEXT PRIMARY KEY,
            valor   TEXT
        )
    """)

    # Configuración por defecto (solo si no existe ya)
    defaults = {
        "n_pathloss": "3.223",
        "n_muestras": "10",
        "mqtt_broker": "192.168.2.2",
        "mqtt_port": "1883",
        "mqtt_user": "user",
        "mqtt_password": "password",
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


def eliminar_esp32(esp_id):
    """Elimina un ESP32 por id."""
    conn = get_connection()
    conn.execute("DELETE FROM esp32 WHERE id = ?", (esp_id,))
    conn.commit()
    conn.close()


# ============================================================
# CONFIG GLOBAL
# ============================================================

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
