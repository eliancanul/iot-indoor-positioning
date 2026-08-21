import sys
import types
import tempfile
import unittest
from pathlib import Path

mqtt = types.ModuleType('paho.mqtt.client')
mqtt.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
mqtt.Client = object
sys.modules.setdefault('paho', types.ModuleType('paho'))
sys.modules.setdefault('paho.mqtt', types.ModuleType('paho.mqtt'))
sys.modules['paho.mqtt.client'] = mqtt

import database as db
from mqtt_manager import quality_report


class RssiQualityPolicyTest(unittest.TestCase):
    def test_default_policy_accepts_a_dirty_but_usable_window(self):
        windows = [
            [-70, -70, -70, -70, -70, -70, -70, -70, -70, -84],
            [-65, -65, -65, -65, -65, -65, -65, -65, -65, -79],
            [-75, -75, -75, -75, -75, -75, -75, -75, -75, -89],
        ]
        report = quality_report(windows)
        self.assertTrue(report['accepted'])

    def test_default_policy_rejects_rssi_spread_above_six_db_std(self):
        windows = [
            [-70, -70, -70, -70, -70, -70, -70, -70, -70, -91],
            [-65, -65, -65, -65, -65, -65, -65, -65, -65, -86],
            [-75, -75, -75, -75, -75, -75, -75, -75, -75, -96],
        ]
        report = quality_report(windows)
        self.assertFalse(report['accepted'])
        self.assertIn('high_std', report['reasons'])

    def test_default_policy_rejects_iqr_above_ten_db(self):
        windows = [
            [-76, -76, -76, -70, -70, -70, -70, -64, -64, -64],
            [-71, -71, -71, -65, -65, -65, -65, -59, -59, -59],
            [-81, -81, -81, -75, -75, -75, -75, -69, -69, -69],
        ]
        report = quality_report(windows)
        self.assertFalse(report['accepted'])
        self.assertIn('high_iqr', report['reasons'])

    def test_database_exposes_the_quality_policy_defaults(self):
        previous = db.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            db.DB_PATH = str(Path(temp) / 'quality.db')
            db.init_db()
            self.assertEqual(float(db.get_config('max_iqr_db')), 10.0)
            self.assertEqual(float(db.get_config('max_std_db')), 6.0)
        db.DB_PATH = previous


if __name__ == '__main__':
    unittest.main()
