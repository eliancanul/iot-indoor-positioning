import tempfile
import unittest
from pathlib import Path
import database as db

class SQLiteConnectionResilienceTest(unittest.TestCase):
    def test_connections_wait_for_short_write_locks(self):
        previous = db.DB_PATH
        with tempfile.TemporaryDirectory() as temp:
            db.DB_PATH = str(Path(temp) / 'lock.db')
            db.init_db()
            conn = db.get_connection()
            timeout_ms = conn.execute('PRAGMA busy_timeout').fetchone()[0]
            conn.close()
            self.assertGreaterEqual(timeout_ms, 20000)
        db.DB_PATH = previous

if __name__ == '__main__':
    unittest.main()
