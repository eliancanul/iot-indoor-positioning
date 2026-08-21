import sqlite3
import tempfile
import unittest
from pathlib import Path
import database as db


class DatabaseSchemaTest(unittest.TestCase):
    def test_normalized_collection_and_model_records(self):
        tmp_path = Path(tempfile.mkdtemp())
        db.DB_PATH = str(tmp_path / 'test.db')
        db.init_db()
        ok, area_id = db.crear_area('Test', 6, 8)
        self.assertTrue(ok)

        tables = {r[0] for r in db.get_connection().execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        self.assertTrue({
            'collection_sessions', 'fingerprint_samples', 'fingerprint_readings',
            'model_registry', 'position_estimates'
        } <= tables)

        session_id = db.crear_sesion(
            area_id=area_id, beacon_id='beacon-a',
            environment_tag='controlada', operator_notes='test',
            node_schema_hash='schema-v1'
        )
        sample_id = db.crear_muestra_fingerprint(
            session_id=session_id, area_id=area_id, cycle_number=1,
            x_real=2.0, y_real=3.0,
            x_tri=1.0, y_tri=2.0, x_circ=1.5, y_circ=2.5,
        )
        db.guardar_lectura_fingerprint(
            sample_id=sample_id, node_id='ESP32_0',
            rssi_median=-70.0, rssi_iqr=2.0, rssi_std=1.2,
            rssi_min=-73.0, rssi_max=-68.0, reading_count=10,
            raw_values=[-70, -68, -73], present=True,
        )
        model_id = db.registrar_modelo(
            area_id=area_id, algorithm='weighted_knn', artifact_path='artifacts/a.joblib',
            feature_schema_hash='schema-v1', dataset_hash='data-v1',
            training_sessions=[session_id], metrics={'mae': 0.8}, is_active=True,
        )
        estimate_id = db.guardar_estimacion(
            sample_id=sample_id, method='fingerprinting_knn',
            x_estimated=2.1, y_estimated=2.9, error_m=0.1414,
            confidence=0.9, model_id=model_id, latency_ms=2.5,
        )

        conn = db.get_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM collection_sessions').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM fingerprint_samples').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM fingerprint_readings').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM model_registry').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM position_estimates').fetchone()[0], 1)
        self.assertEqual(
            conn.execute('SELECT raw_values_json FROM fingerprint_readings WHERE id=1').fetchone()[0],
            '[-70,-68,-73]'
        )
        self.assertEqual(
            tuple(conn.execute(
                'SELECT x_tri, y_tri, trian_x, triang_y, x_circ, y_circ '
                'FROM fingerprint_samples WHERE id=?', (sample_id,)
            ).fetchone()),
            (1.0, 2.0, 1.0, 2.0, 1.5, 2.5),
        )
        self.assertGreater(estimate_id, 0)


if __name__ == "__main__":
    unittest.main()
