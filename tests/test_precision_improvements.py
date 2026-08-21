import sys
import types
import tempfile
import unittest
from pathlib import Path

# UI/network dependencies are irrelevant to math and DB behavior under test.
st = types.ModuleType('streamlit')
sys.modules['streamlit'] = st
mqtt = types.ModuleType('paho.mqtt.client')
mqtt.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
mqtt.Client = object
sys.modules['paho'] = types.ModuleType('paho')
sys.modules['paho.mqtt'] = types.ModuleType('paho.mqtt')
sys.modules['paho.mqtt.client'] = mqtt

import database as db
from mqtt_manager import quality_report, disRSSI
from calibration import fit_pathloss_per_node


class PrecisionImprovementsTest(unittest.TestCase):
    def setUp(self):
        self.old = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = str(Path(self.temp.name) / 'precision.db')
        db.init_db()
        ok, self.area_id = db.crear_area('test', 5, 2, 0, 0)
        self.assertTrue(ok)
        ok, self.esp_id = db.crear_esp32('N0', 'T0', 0, 0, -60, self.area_id)
        self.assertTrue(ok)

    def tearDown(self):
        db.DB_PATH = self.old
        self.temp.cleanup()

    def test_per_node_pathloss_is_persisted_and_used(self):
        db.actualizar_calibracion_nodo(self.esp_id, n_pathloss=2.0)
        node = db.obtener_esp32(self.esp_id)
        self.assertEqual(node['n_pathloss'], 2.0)
        self.assertAlmostEqual(disRSSI(-80, -60, node['n_pathloss']), 10.0)

    def test_regression_fits_node_specific_a_and_n(self):
        fit = fit_pathloss_per_node([(1, -60), (2, -66.0206), (4, -72.0412)])
        self.assertAlmostEqual(fit['rssi_1m'], -60.0, places=2)
        self.assertAlmostEqual(fit['n_pathloss'], 2.0, places=2)
        self.assertLess(fit['rmse_db'], 0.01)

    def test_noisy_window_is_flagged(self):
        report = quality_report([[-70, -70, -70, -70], [-80, -80, -80, -80], [-60, -85, -60, -85]])
        self.assertFalse(report['accepted'])
        self.assertIn('high_iqr', report['reasons'])

    def test_stable_window_is_accepted(self):
        report = quality_report([[-70, -71, -70, -70], [-80, -80, -81, -80], [-60, -61, -60, -60]])
        self.assertTrue(report['accepted'])
        self.assertEqual(report['reasons'], [])


if __name__ == '__main__':
    unittest.main()
