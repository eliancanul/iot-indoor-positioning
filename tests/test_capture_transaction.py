import tempfile
import unittest
from pathlib import Path
import database as db


class CaptureTransactionTest(unittest.TestCase):
    def setUp(self):
        self.old_path = db.DB_PATH
        self.tmpdir = tempfile.TemporaryDirectory()
        db.DB_PATH = str(Path(self.tmpdir.name) / 'capture.db')
        db.init_db()
        ok, self.area_id = db.crear_area('test', 8, 6, 2, 1)
        self.assertTrue(ok)
        for node_id, topic, x, y in [('n0', 't0', 0, 0), ('n1', 't1', 5, 0), ('n2', 't2', 0, 2)]:
            ok, _ = db.crear_esp32(node_id, topic, x, y, -60, self.area_id)
            self.assertTrue(ok)

    def tearDown(self):
        db.DB_PATH = self.old_path
        self.tmpdir.cleanup()

    def test_atomic_cycle_persists_one_sample_three_readings_and_estimates(self):
        result = db.guardar_ciclo_captura(
            area_id=self.area_id, session_id=None, cycle_id='cycle-unique-1',
            x_real=2, y_real=1,
            readings=[
                {'node_id': 'n0', 'rssi_values': [-60] * 10, 'captured_at': 100.0},
                {'node_id': 'n1', 'rssi_values': [-70] * 10, 'captured_at': 101.0},
                {'node_id': 'n2', 'rssi_values': [-65] * 10, 'captured_at': 100.5},
            ],
            estimates={'triangulos': (2.0, 1.0), 'circulos': (2.0, 1.0)},
            max_window_skew_s=2.0,
        )
        self.assertTrue(result['saved'])
        self.assertEqual(result['reading_count'], 3)
        self.assertEqual(result['estimate_count'], 2)
        conn = db.get_connection()
        timing = conn.execute(
            'SELECT window_start_at, window_end_at, window_skew_s '
            'FROM fingerprint_samples'
        ).fetchone()
        conn.close()
        self.assertEqual(timing['window_skew_s'], 1.0)
        self.assertTrue(timing['window_start_at'])
        self.assertTrue(timing['window_end_at'])
        self.assertFalse(db.guardar_ciclo_captura(
            area_id=self.area_id, session_id=None, cycle_id='cycle-unique-1', x_real=2, y_real=1,
            readings=[], estimates={}, max_window_skew_s=2.0)['saved'])

    def test_skewed_cycle_is_preserved_as_dirty_without_partial_writes(self):
        result = db.guardar_ciclo_captura(
            area_id=self.area_id, session_id=None, cycle_id='skewed', x_real=2, y_real=1,
            readings=[
                {'node_id': 'n0', 'rssi_values': [-60], 'captured_at': 100.0},
                {'node_id': 'n1', 'rssi_values': [-70], 'captured_at': 104.5},
                {'node_id': 'n2', 'rssi_values': [-65], 'captured_at': 101.0},
            ], estimates={}, max_window_skew_s=2.0,
        )
        self.assertTrue(result['saved'])
        self.assertEqual(result['quality_status'], 'dirty')
        self.assertIn('window_skew_exceeded', result['quality_reasons'])
        conn = db.get_connection()
        self.assertEqual(conn.execute('select count(*) from fingerprint_samples').fetchone()[0], 1)
        row = conn.execute(
            'SELECT quality_status, quality_reasons_json, window_skew_s '
            'FROM fingerprint_samples'
        ).fetchone()
        conn.close()
        self.assertEqual(row['quality_status'], 'dirty')
        self.assertIn('window_skew_exceeded', row['quality_reasons_json'])
        self.assertEqual(row['window_skew_s'], 4.5)

    def test_closed_session_rejects_new_cycles(self):
        session_id = db.crear_sesion(
            area_id=self.area_id,
            beacon_id='beacon-closed',
            environment_tag='legacy',
            node_schema_hash='n0|n1|n2',
        )
        db.cerrar_sesion(session_id)

        with self.assertRaises(ValueError):
            db.guardar_ciclo_captura(
                area_id=self.area_id,
                session_id=session_id,
                cycle_id='closed-session-cycle',
                x_real=2,
                y_real=1,
                readings=[
                    {'node_id': 'n0', 'rssi_values': [-60], 'captured_at': 100.0},
                    {'node_id': 'n1', 'rssi_values': [-70], 'captured_at': 100.0},
                    {'node_id': 'n2', 'rssi_values': [-65], 'captured_at': 100.0},
                ],
                estimates={},
            )

        conn = db.get_connection()
        self.assertEqual(
            conn.execute('SELECT COUNT(*) FROM fingerprint_samples').fetchone()[0],
            0,
        )
        conn.close()

    def test_dirty_quality_is_preserved_for_derived_audit(self):
        result = db.guardar_ciclo_captura(
            area_id=self.area_id, session_id=None, cycle_id='dirty-quality', x_real=2, y_real=1,
            readings=[
                {'node_id': 'n0', 'rssi_values': [-60], 'captured_at': 100.0},
                {'node_id': 'n1', 'rssi_values': [-70], 'captured_at': 100.0},
                {'node_id': 'n2', 'rssi_values': [-65], 'captured_at': 100.0},
            ], estimates={}, max_window_skew_s=2.0,
            quality_status='dirty', quality_reasons=['high_iqr'],
        )
        self.assertTrue(result['saved'])
        self.assertEqual(result['quality_status'], 'dirty')
        conn = db.get_connection()
        row = conn.execute(
            'SELECT quality_status, quality_reasons_json FROM fingerprint_samples '
            'WHERE id=?', (result['sample_id'],)
        ).fetchone()
        readings = conn.execute(
            'SELECT COUNT(*) FROM fingerprint_readings WHERE sample_id=?',
            (result['sample_id'],),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(row['quality_status'], 'dirty')
        self.assertIn('high_iqr', row['quality_reasons_json'])
        self.assertEqual(readings, 3)


if __name__ == '__main__':
    unittest.main()
