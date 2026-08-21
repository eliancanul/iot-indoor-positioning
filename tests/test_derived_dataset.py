import csv
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import database as db
from tools.derive_dataset import derive_dataset


class DerivedDatasetTest(unittest.TestCase):
    def setUp(self):
        self.previous_path = db.DB_PATH
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        db.DB_PATH = str(self.root / "capture.db")
        db.init_db()
        ok, self.area_id = db.crear_area("Laboratorio", 4, 2, 2, 1)
        self.assertTrue(ok)
        self.campaign_id = db.crear_campana(
            area_id=self.area_id,
            codigo="campaign-01",
            descripcion="Campaña de prueba",
            condiciones_ambientales="Controladas",
            orden_posiciones=[(0, 0), (1, 0)],
        )
        self.session_ids = [
            db.crear_sesion_captura(
                campaign_id=self.campaign_id,
                area_id=self.area_id,
                orientation="north",
                environment_tag="baseline-v1",
                layout_version="layout-v1",
                independence_evidence=f"Sesión física {index}: recolocación y horario distinto",
                obstacle_description="Sin obstáculos",
                node_schema_hash="N0|N1|N2",
            )
            for index in range(1, 4)
        ]
        self._insert_samples()

    def tearDown(self):
        db.DB_PATH = self.previous_path
        self.tempdir.cleanup()

    def _insert_sample(self, session_id, cycle_number, x, y, captured_at, iqr=2.0):
        conn = db.get_connection()
        cur = conn.execute(
            """INSERT INTO fingerprint_samples(
                   session_id, area_id, captured_at, cycle_number, x_real, y_real)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, self.area_id, captured_at, cycle_number, x, y),
        )
        sample_id = cur.lastrowid
        for node_id, median in (("N0", -70.0), ("N1", -80.0), ("N2", -90.0)):
            conn.execute(
                """INSERT INTO fingerprint_readings(
                       sample_id, node_id, rssi_median, rssi_iqr, rssi_std,
                       rssi_min, rssi_max, reading_count, raw_values_json, present)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (sample_id, node_id, median, iqr, 1.0, median - 2, median + 2, 10,
                 f"[{median},{median - 1},{median - 2}]")
            )
        conn.commit()
        conn.close()

    def _insert_samples(self):
        # Thirty-one eligible samples across three independent sessions.
        for index in range(31):
            session_id = self.session_ids[index % 3]
            self._insert_sample(
                session_id=session_id,
                cycle_number=index + 1,
                x=0,
                y=0,
                captured_at=f"2026-01-01 00:00:{index + 1:02d}",
            )
        # One dirty sample remains auditable but must not enter training.
        self._insert_sample(
            session_id=self.session_ids[0],
            cycle_number=99,
            x=0,
            y=0,
            captured_at="2026-01-01 00:01:00",
            iqr=11.0,
        )
        # Fewer than thirty samples: this position must not be covered.
        for index in range(29):
            self._insert_sample(
                session_id=self.session_ids[index % 3],
                cycle_number=index + 1,
                x=1,
                y=0,
                captured_at=f"2026-01-02 00:00:{index + 1:02d}",
            )

    def test_export_classifies_preserves_and_balances_without_mutating_source(self):
        before = Path(db.DB_PATH).read_bytes()
        first = derive_dataset(str(db.DB_PATH), self.root / "export-1")
        second = derive_dataset(str(db.DB_PATH), self.root / "export-2")

        self.assertEqual(first["training_sample_count"], 30)
        self.assertEqual(first["eligible_count"], 60)
        self.assertEqual(first["dirty_count"], 1)
        self.assertEqual(first["covered_positions"], [[0.0, 0.0]])
        coverage = {tuple(item["position"]): item for item in first["coverage"]}
        self.assertEqual(coverage[(0.0, 0.0)]["status"], "covered")
        self.assertEqual(coverage[(1.0, 0.0)]["status"], "insufficient_samples")
        self.assertTrue(Path(first["coverage_report"]).is_file())
        self.assertEqual(Path(db.DB_PATH).read_bytes(), before)
        self.assertEqual(
            Path(first["training_csv"]).read_bytes(),
            Path(second["training_csv"]).read_bytes(),
        )
        self.assertEqual(first["content_sha256"], second["content_sha256"])

        with Path(first["training_csv"]).open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 30)
        self.assertEqual({(row["x_real"], row["y_real"]) for row in rows}, {("0.0", "0.0")})
        self.assertNotIn("x_real", first["feature_columns"])
        self.assertNotIn("y_real", first["feature_columns"])

        manifest = Path(first["manifest"]).read_text(encoding="utf-8")
        self.assertIn('"policy_version": "rssi-policy-v1"', manifest)
        self.assertEqual(hashlib.sha256(Path(first["training_csv"]).read_bytes()).hexdigest(), first["content_sha256"])

    def test_coverage_reports_position_session_and_campaign_counts(self):
        result = derive_dataset(str(db.DB_PATH), self.root / "coverage")
        coverage = json.loads(Path(result["coverage_report"]).read_text(encoding="utf-8"))

        positions = {tuple(item["position"]): item for item in coverage["positions"]}
        self.assertEqual(positions[(0.0, 0.0)]["eligible"], 31)
        self.assertEqual(positions[(0.0, 0.0)]["dirty"], 1)
        self.assertEqual(positions[(0.0, 0.0)]["session_count"], 3)
        self.assertEqual(positions[(0.0, 0.0)]["campaign_count"], 1)
        self.assertEqual(
            positions[(0.0, 0.0)]["session_ids"],
            sorted(self.session_ids),
        )
        self.assertEqual(
            positions[(0.0, 0.0)]["campaign_ids"],
            [self.campaign_id],
        )

        sessions = {item["session_id"]: item for item in coverage["sessions"]}
        self.assertEqual(set(sessions), set(self.session_ids))
        self.assertEqual(sum(item["eligible"] for item in sessions.values()), 60)
        self.assertEqual(sum(item["dirty"] for item in sessions.values()), 1)

        campaigns = {item["campaign_id"]: item for item in coverage["campaigns"]}
        self.assertEqual(set(campaigns), {self.campaign_id})
        self.assertEqual(campaigns[self.campaign_id]["eligible"], 60)
        self.assertEqual(campaigns[self.campaign_id]["dirty"], 1)
        self.assertEqual(coverage["status_counts"], {"covered": 1, "insufficient_samples": 1})

        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertIn("sessions", manifest["coverage"])
        self.assertIn("campaigns", manifest["coverage"])
        self.assertIn("status_counts", manifest["coverage"])


if __name__ == "__main__":
    unittest.main()
