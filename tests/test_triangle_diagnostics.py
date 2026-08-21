import tempfile
import unittest
from pathlib import Path
import database as db

class TriangleDiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.old = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = str(Path(self.temp.name) / 'diag.db')
        db.init_db()
        ok, self.area_id = db.crear_area('test', 5, 2, 2, 1)
        self.assertTrue(ok)
        for node_id, topic, x, y in [('N0','T0',0,0),('N1','T1',5,0),('N2','T2',0,2)]:
            self.assertTrue(db.crear_esp32(node_id, topic, x, y, -60, self.area_id)[0])

    def tearDown(self):
        db.DB_PATH = self.old
        self.temp.cleanup()

    def test_invalid_triangle_is_persisted_as_diagnostic_not_fake_coordinate(self):
        result = db.guardar_ciclo_captura(
            area_id=self.area_id, session_id=None, cycle_id='diag-1', x_real=2, y_real=1,
            readings=[
                {'node_id':'N0','rssi_values':[-60]*10,'captured_at':1},
                {'node_id':'N1','rssi_values':[-70]*10,'captured_at':1},
                {'node_id':'N2','rssi_values':[-65]*10,'captured_at':1},
            ],
            estimates={'circulos':(2.0,1.0)}, max_window_skew_s=20,
            invalid_estimates=[{'method':'triangulos','reason':'incompatible_ranges',
                                'raw_x':6.2,'raw_y':8.8,'residual_m':4.4}],
        )
        self.assertTrue(result['saved'])
        conn = db.get_connection()
        row = conn.execute('select method,status,reason,raw_x,raw_y,residual_m from position_estimate_diagnostics').fetchone()
        conn.close()
        self.assertEqual(tuple(row), ('triangulos','invalid','incompatible_ranges',6.2,8.8,4.4))

if __name__ == '__main__':
    unittest.main()
