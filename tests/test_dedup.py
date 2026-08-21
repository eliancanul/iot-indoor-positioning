import tempfile
import unittest
from pathlib import Path
import database as db

class DedupTest(unittest.TestCase):
    def test_same_cycle_signature_is_claimed_only_once(self):
        db.DB_PATH = str(Path(tempfile.mkdtemp()) / 'test.db')
        db.init_db()
        signature = 'area=4|x=2|y=1|rssi=-83,-90,-82.5|ts=2026-08-13 16:41:54'
        self.assertTrue(db.claim_cycle_signature(signature))
        self.assertFalse(db.claim_cycle_signature(signature))

if __name__ == '__main__':
    unittest.main()
