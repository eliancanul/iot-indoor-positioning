import tempfile
import unittest
from pathlib import Path
import database as db

class CaptureTimingDefaultTest(unittest.TestCase):
    def test_default_window_skew_matches_asynchronous_esp_publish_rates(self):
        old = db.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            db.DB_PATH = str(Path(temp) / 'test.db')
            db.init_db()
            self.assertEqual(float(db.get_config('max_window_skew_s')), 20.0)
        db.DB_PATH = old

if __name__ == '__main__':
    unittest.main()
