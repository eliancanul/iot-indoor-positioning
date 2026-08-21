import sqlite3
import tempfile
import unittest
from pathlib import Path

import database as db


class CaptureMetadataTest(unittest.TestCase):
    def setUp(self):
        self.previous_path = db.DB_PATH
        self.tempdir = tempfile.TemporaryDirectory()
        db.DB_PATH = str(Path(self.tempdir.name) / "capture.db")
        db.init_db()
        ok, self.area_id = db.crear_area("Laboratorio", 4, 2, 2, 1)
        self.assertTrue(ok)

    def tearDown(self):
        db.DB_PATH = self.previous_path
        self.tempdir.cleanup()

    def test_physical_campaign_and_session_store_required_capture_context(self):
        campaign_id = db.crear_campana(
            area_id=self.area_id,
            codigo="campaign-01",
            descripcion="Campaña base del radio-map",
            condiciones_ambientales="Sala despejada, puerta cerrada",
            orden_posiciones=[(0, 0), (1, 0), (2, 0)],
        )

        session_id = db.crear_sesion_captura(
            campaign_id=campaign_id,
            area_id=self.area_id,
            orientation="north",
            environment_tag="baseline-v1",
            layout_version="layout-v1",
            independence_evidence="Horario distinto y recolocación del dispositivo",
            obstacle_description="Sin obstáculos añadidos",
            operator_notes="Sesión de prueba",
            node_schema_hash="N0|N1|N2",
        )

        conn = db.get_connection()
        campaign = conn.execute(
            "SELECT codigo, descripcion, condiciones_ambientales, orden_posiciones_json "
            "FROM capture_campaigns WHERE id=?",
            (campaign_id,),
        ).fetchone()
        session = conn.execute(
            "SELECT campaign_id, orientation, environment_tag, layout_version, "
            "independence_evidence, obstacle_description "
            "FROM collection_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        conn.close()

        self.assertEqual(campaign["codigo"], "campaign-01")
        self.assertEqual(campaign["condiciones_ambientales"], "Sala despejada, puerta cerrada")
        self.assertEqual(campaign["orden_posiciones_json"], "[[0.0,0.0],[1.0,0.0],[2.0,0.0]]")
        self.assertEqual(session["campaign_id"], campaign_id)
        self.assertEqual(session["orientation"], "north")
        self.assertEqual(session["environment_tag"], "baseline-v1")
        self.assertEqual(session["layout_version"], "layout-v1")
        self.assertEqual(
            [item["id"] for item in db.listar_sesiones_captura(self.area_id)],
            [session_id],
        )
        self.assertEqual(
            db.obtener_posiciones_campana(campaign_id),
            [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]],
        )

    def test_session_requires_obstacle_description_or_photo_reference(self):
        campaign_id = db.crear_campana(
            area_id=self.area_id,
            codigo="campaign-02",
            descripcion="Campaña",
            condiciones_ambientales="Controladas",
            orden_posiciones=[(0, 0)],
        )

        with self.assertRaises(ValueError):
            db.crear_sesion_captura(
                campaign_id=campaign_id,
                area_id=self.area_id,
                orientation="unknown",
                environment_tag="baseline-v1",
                layout_version="layout-v1",
                independence_evidence="Recolocación",
            )

    def test_existing_normalized_schema_remains_readable_after_additive_setup(self):
        conn = db.get_connection()
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(collection_sessions)")
        }
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        conn.close()

        self.assertIn("capture_campaigns", tables)
        self.assertTrue(
            {
                "campaign_id",
                "orientation",
                "environment_tag",
                "layout_version",
                "independence_evidence",
                "obstacle_description",
                "obstacle_photo_ref",
            } <= columns
        )

    def test_additive_setup_preserves_an_old_session_row(self):
        old_path = Path(self.tempdir.name) / "old.db"
        db.DB_PATH = str(old_path)
        conn = sqlite3.connect(old_path)
        conn.executescript(
            """
            CREATE TABLE areas (id INTEGER PRIMARY KEY, nombre TEXT, ancho REAL,
                                alto REAL, punto_real_x REAL, punto_real_y REAL);
            CREATE TABLE collection_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                area_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                beacon_id TEXT,
                environment_tag TEXT,
                operator_notes TEXT,
                node_schema_hash TEXT NOT NULL
            );
            INSERT INTO areas VALUES (7, 'Histórica', 4, 2, 2, 1);
            INSERT INTO collection_sessions
                (area_id, started_at, environment_tag, node_schema_hash)
                VALUES (7, '2026-01-01 00:00:00', 'live', 'N0|N1|N2');
            """
        )
        conn.commit()
        conn.close()

        db.init_db()
        conn = db.get_connection()
        row = conn.execute(
            "SELECT area_id, environment_tag, node_schema_hash, orientation "
            "FROM collection_sessions WHERE id=1"
        ).fetchone()
        columns = {
            item[1] for item in conn.execute(
                "PRAGMA table_info(collection_sessions)"
            )
        }
        conn.close()

        self.assertEqual(tuple(row[:3]), (7, "live", "N0|N1|N2"))
        self.assertIsNone(row["orientation"])
        self.assertIn("campaign_id", columns)


if __name__ == "__main__":
    unittest.main()
