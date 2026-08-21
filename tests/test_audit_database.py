import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.audit_database import audit_database


class AuditDatabaseTest(unittest.TestCase):
    def test_audit_is_read_only_and_reports_counts_and_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE areas (id INTEGER PRIMARY KEY);
                CREATE TABLE esp32 (id INTEGER PRIMARY KEY);
                CREATE TABLE dataset (id INTEGER PRIMARY KEY);
                CREATE TABLE collection_sessions (id INTEGER, area_id INTEGER);
                CREATE TABLE fingerprint_samples
                    (id INTEGER, session_id INTEGER, area_id INTEGER,
                     captured_at TEXT, cycle_number INTEGER,
                     x_real REAL, y_real REAL);
                CREATE TABLE fingerprint_readings
                    (sample_id INTEGER, node_id TEXT, rssi_median REAL,
                     rssi_iqr REAL, rssi_std REAL, rssi_min REAL,
                     rssi_max REAL, reading_count INTEGER);
                INSERT INTO collection_sessions VALUES (1, 7);
                INSERT INTO fingerprint_samples
                    VALUES (1, 1, 7, '2026-01-01 00:00:01', 1, 2, 3);
                INSERT INTO fingerprint_readings VALUES
                    (1, 'N0', -70, 2, 1, -72, -68, 10);
                """
            )
            conn.commit()
            before = path.read_bytes()
            conn.close()

            report = audit_database(str(path))

            self.assertTrue(report["read_only"])
            self.assertEqual(report["counts"]["fingerprint_samples"], 1)
            self.assertEqual(report["sessions_by_area"], {"7": 1})
            self.assertEqual(report["quality"]["invalid_rssi_values"], 0)
            self.assertEqual(path.read_bytes(), before)

    def test_reconciliation_accounts_matched_and_unmatched_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reconcile.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE areas (id INTEGER PRIMARY KEY);
                CREATE TABLE esp32 (id INTEGER PRIMARY KEY);
                CREATE TABLE dataset (
                    id INTEGER PRIMARY KEY, timestamp TEXT, area_id INTEGER,
                    rssi_1 REAL, rssi_2 REAL, rssi_3 REAL,
                    x_real REAL, y_real REAL
                );
                CREATE TABLE collection_sessions (id INTEGER, area_id INTEGER);
                CREATE TABLE fingerprint_samples
                    (id INTEGER, session_id INTEGER, area_id INTEGER,
                     captured_at TEXT, cycle_number INTEGER,
                     x_real REAL, y_real REAL);
                CREATE TABLE fingerprint_readings
                    (sample_id INTEGER, node_id TEXT, rssi_median REAL,
                     rssi_iqr REAL, rssi_std REAL, rssi_min REAL,
                     rssi_max REAL, reading_count INTEGER);
                INSERT INTO collection_sessions VALUES (1, 7);
                INSERT INTO fingerprint_samples VALUES
                    (1, 1, 7, '2026-01-01 00:00:01', 1, 2, 3),
                    (2, 1, 7, '2026-01-01 00:00:02', 2, 4, 5);
                INSERT INTO fingerprint_readings VALUES
                    (1, 'N0', -70, 2, 1, -72, -68, 10),
                    (1, 'N1', -80, 2, 1, -82, -78, 10),
                    (1, 'N2', -90, 2, 1, -92, -88, 10),
                    (2, 'N0', -71, 2, 1, -73, -69, 10),
                    (2, 'N1', -81, 2, 1, -83, -79, 10),
                    (2, 'N2', -91, 2, 1, -93, -89, 10);
                INSERT INTO dataset VALUES
                    (10, '2026-01-01 00:00:01', 7, -70, -80, -90, 2, 3),
                    (11, '2026-01-01 00:00:03', 7, -72, -82, -92, 6, 7);
                """
            )
            conn.commit()
            conn.close()

            report = audit_database(str(path))
            reconciliation = report["reconciliation"]

            self.assertEqual(reconciliation["matched"], 1)
            self.assertEqual(reconciliation["normalized_only"], 1)
            self.assertEqual(reconciliation["legacy_only"], 1)
            self.assertEqual(reconciliation["ambiguous"], 0)
            self.assertEqual(
                reconciliation["accounting"],
                {"normalized": 2, "legacy": 2},
            )


if __name__ == "__main__":
    unittest.main()
