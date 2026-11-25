import copy
import csv
import hashlib
import io
import json
import math
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import database as db
from positioning import (DatasetError, FEATURES, FingerprintModel, compare, error_metrics,
                         load_export, make_demo, split_dataset)
from tools.derive_dataset import derive_dataset


class ModelsTest(unittest.TestCase):
    def setUp(self):
        self.demo = make_demo()

    def test_demo_is_deterministic_and_explicitly_synthetic(self):
        self.assertEqual(self.demo.provenance, make_demo().provenance)
        self.assertEqual(self.demo.provenance['kind'], 'synthetic')
        np.testing.assert_array_equal(self.demo.X, make_demo().X)

    def test_session_split_is_disjoint_and_reproducible(self):
        a, b, meta = split_dataset(self.demo)
        c, d, again = split_dataset(self.demo)
        np.testing.assert_array_equal(a, c)
        np.testing.assert_array_equal(b, d)
        self.assertEqual(meta, again)
        self.assertFalse({self.demo.rows[i]['session_id'] for i in a} & {self.demo.rows[i]['session_id'] for i in b})
        self.assertFalse(set(meta['train_ids']) & set(meta['test_ids']))

    def test_campaign_split_wins_over_sessions(self):
        for row in self.demo.rows:
            row['campaign_id'] = 'campaign-' + row['session_id'][-1]
        a, b, meta = split_dataset(self.demo)
        self.assertEqual(meta['group_by'], 'campaign_id')
        self.assertFalse({self.demo.rows[i]['campaign_id'] for i in a} & {self.demo.rows[i]['campaign_id'] for i in b})

    def test_spatial_holdout_excludes_position_and_session(self):
        a, b, meta = split_dataset(self.demo, 'spatial', (2, 1))
        self.assertTrue(all(tuple(self.demo.y[i]) != (2, 1) for i in a))
        self.assertTrue(all(tuple(self.demo.y[i]) == (2, 1) for i in b))
        self.assertTrue(meta['unused_ids'])
        self.assertFalse({self.demo.rows[i]['session_id'] for i in a} & {self.demo.rows[i]['session_id'] for i in b})
        self.assertEqual(len(a)+len(b)+len(meta['unused_ids']), len(self.demo.rows))

    def test_unknown_holdout_and_single_group_fail(self):
        with self.assertRaises(DatasetError):
            split_dataset(self.demo, 'spatial', (99, 2))
        for row in self.demo.rows:
            row['session_id'] = 'one'
        with self.assertRaises(DatasetError):
            split_dataset(self.demo)

    def test_scaler_fits_train_only_and_features_exclude_targets(self):
        a, b, _ = split_dataset(self.demo)
        model = FingerprintModel().fit(self.demo.X[a], self.demo.y[a], ['a', 'b', 'c'])
        np.testing.assert_allclose(model.scaler.mean_, self.demo.X[a].mean(axis=0))
        self.assertEqual(FEATURES, ('anchor_1_rssi_median', 'anchor_2_rssi_median', 'anchor_3_rssi_median'))
        self.assertFalse(np.array_equal(model.scaler.mean_, self.demo.X.mean(axis=0)))

    def test_exact_match_averages_all_duplicate_fingerprints(self):
        model = FingerprintModel(k=1).fit([[-60]*3, [-60]*3, [-90]*3], [[0, 0], [2, 2], [4, 2]], ['a','b','c'])
        np.testing.assert_allclose(model.predict([[-60]*3]), [[1, 1]])

    def test_tree_is_binary_deterministic_and_bounded(self):
        m = FingerprintModel('tree').fit(self.demo.X, self.demo.y, ['a','b','c'])
        n = FingerprintModel('tree').fit(self.demo.X, self.demo.y, ['a','b','c'])
        np.testing.assert_array_equal(m.predict(self.demo.X), n.predict(self.demo.X))
        self.assertTrue((m.predict([[-149, -149, -149]]) >= 0).all())
        self.assertLessEqual(m.tree.get_depth(), 6)
        self.assertEqual(len(m.tree.tree_.children_left), len(m.tree.tree_.children_right))

    def test_missing_unknown_nonfinite_and_no_training_fail(self):
        m = FingerprintModel()
        with self.assertRaises(DatasetError):
            m.locate({'a': -50})
        with self.assertRaises(DatasetError):
            m.fit([[-50]*3], [[1,1]], ['a','b','c'])
        m.fit([[-50]*3, [-80]*3], [[0,0],[4,2]], ['a','b','c'])
        for readings in ({'a':-60,'b':-60}, {'a':-60,'b':-60,'bad':-60}, {'a':float('nan'),'b':-60,'c':-60}, {'a':20,'b':-60,'c':-60}):
            with self.subTest(readings=readings), self.assertRaises(DatasetError):
                m.locate(readings)
        self.assertTrue(m.locate({'a':-100,'b':-100,'c':-100})['outside_training_rssi'])

    def test_metrics_have_real_units_and_correct_percentile(self):
        result = error_metrics([0, 1, 2, 3, 4])
        self.assertEqual(result['mean_m'], 2)
        self.assertEqual(result['median_m'], 2)
        self.assertAlmostEqual(result['p90_m'], 3.6)
        self.assertIsNone(error_metrics([])['mean_m'])

    def test_comparison_same_rows_no_target_leakage_and_finite_json(self):
        report = compare(self.demo)
        self.assertEqual(report, compare(self.demo))
        self.assertEqual({m['n'] for m in report['metrics'].values()}, {45})
        ids = [{s['sample_id'] for s in report['samples'] if s['method'] == m} for m in report['metrics']]
        self.assertTrue(ids[0] == ids[1] == ids[2])
        self.assertEqual(report['features'], list(FEATURES))
        json.dumps(report, allow_nan=False)

    def test_baseline_failure_reports_common_denominator_not_better_error(self):
        with patch('mqtt_manager.circulos', return_value=None):
            report = compare(self.demo)
        self.assertTrue(all(m['n'] == 0 and m['mean_m'] is None for m in report['metrics'].values()))
        self.assertEqual(report['metrics']['circles']['coverage'], 0)
        self.assertEqual(report['metrics']['wknn']['available'], 45)
        json.dumps(report, allow_nan=False)


class ExportGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        previous = db.DB_PATH
        db.DB_PATH = str(cls.root/'synthetic.db')
        try:
            db.init_db()
            ok, area = db.crear_area('Synthetic fixture', 4, 2, 2, 1)
            assert ok
            campaign = db.crear_campana(area, 'synthetic', 'Test only', 'Synthetic only', [(x,y) for x in range(5) for y in range(3)])
            connection = db.get_connection()
            for i, (x,y) in enumerate(((0,0),(4,0),(0,2)),1):
                connection.execute('INSERT INTO esp32(node_id, topic, pos_x, pos_y, rssi_1m, n_pathloss, area_id) VALUES(?,?,?,?,?,?,?)', (f'N{i}',f'test/{i}',x,y,-48,2.2,area))
            connection.commit()
            connection.close()
            for s in range(3):
                session = db.crear_sesion_captura(campaign, area, 'north', 'synthetic', 'layout-test', f'Synthetic {s}', obstacle_description='Synthetic', node_schema_hash='N1|N2|N3')
                connection = db.get_connection()
                cycle = 0
                for x in range(5):
                    for y in range(3):
                        for r in range(10):
                            cycle += 1
                            sample = connection.execute('INSERT INTO fingerprint_samples(session_id,area_id,cycle_number,x_real,y_real,window_skew_s) VALUES (?,?,?,?,?,?)', (session,area,cycle,x,y,1)).lastrowid
                            for a in range(1,4):
                                connection.execute('INSERT INTO fingerprint_readings(sample_id,node_id,rssi_median,rssi_iqr,rssi_std,reading_count,present) VALUES (?,?,?,?,?,?,?)', (sample,f'N{a}',-50-x-y-a-r*.1,2,1,10,1))
                connection.commit()
                connection.close()
                db.cerrar_sesion(session)
            before = Path(db.DB_PATH).read_bytes()
            export = derive_dataset(db.DB_PATH, cls.root/'export')
            assert before == Path(db.DB_PATH).read_bytes()
            cls.csv = Path(export['training_csv']).read_bytes()
            cls.manifest = json.loads(Path(export['manifest']).read_bytes())
        finally:
            db.DB_PATH = previous

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def payload(self, change=None, manifest_change=None):
        rows = list(csv.DictReader(io.StringIO(self.csv.decode())))
        manifest = copy.deepcopy(self.manifest)
        if change:
            change(rows)
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
        data = stream.getvalue().encode()
        manifest['training_sha256'] = hashlib.sha256(data).hexdigest()
        if manifest_change:
            manifest_change(manifest)
        return data, json.dumps(manifest).encode()

    def test_roundtrip_with_readonly_source_and_no_private_context(self):
        dataset = load_export(self.csv, json.dumps(self.manifest).encode())
        self.assertEqual(dataset.X.shape, (450,3))
        self.assertEqual(dataset.provenance['kind'], 'measured')
        self.assertEqual(self.manifest['evaluation_context']['blockers'], [])
        self.assertNotIn('independence_evidence', self.manifest['evaluation_context']['sessions'][0])
        self.assertNotIn('obstacle_description', self.manifest['evaluation_context']['sessions'][0])

    def test_corrupt_calibration_blocks_comparison_without_breaking_export(self):
        for value in (None, float('nan'), float('inf'), 'broken', '-2.0', '2.2'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                source = Path(directory)/'synthetic-copy.db'
                shutil.copyfile(self.root/'synthetic.db', source)
                with sqlite3.connect(source) as connection:
                    connection.execute("UPDATE esp32 SET n_pathloss=? WHERE node_id='N1'", (value,))
                before = source.read_bytes()
                exported = derive_dataset(str(source), Path(directory)/'export')
                self.assertEqual(before, source.read_bytes())
                encoded = Path(exported['manifest']).read_bytes()
                self.assertNotIn(b'Infinity', encoded)
                self.assertNotIn(b'NaN', encoded)
                manifest = json.loads(encoded)
                if value == '2.2':
                    self.assertEqual(manifest['evaluation_context']['blockers'], [])
                    load_export(Path(exported['training_csv']).read_bytes(), Path(exported['manifest']).read_bytes())
                else:
                    self.assertTrue(any('calibración' in reason for reason in manifest['evaluation_context']['blockers']))
                    with self.assertRaises(DatasetError):
                        load_export(Path(exported['training_csv']).read_bytes(), Path(exported['manifest']).read_bytes())

    def test_hash_tamper_empty_and_malformed_export_fail(self):
        for data, manifest in ((self.csv+b'\n', json.dumps(self.manifest).encode()), (b'',b'{}'), (b'',b'[]'), (b'',b'invalid')):
            with self.subTest(manifest=manifest[:10]), self.assertRaises(DatasetError):
                load_export(data, manifest)

    def test_invalid_rows_fail_even_with_rehashed_manifest(self):
        mutations = [lambda r: r.pop(), lambda r: r[0].update(sample_id=r[1]['sample_id']),
                     lambda r: r[0].update(x_real=100), lambda r: r[0].update(anchor_1_rssi_median='nan'),
                     lambda r: r[0].update(anchor_1_missing=1), lambda r: r[0].update(status='dirty'),
                     lambda r: r[0].update(window_skew_s=''), lambda r: r[0].update(window_skew_s=21),
                     lambda r: r[0].update(anchor_2_rssi_std=-1), lambda r: r[0].update(area_id=999),
                     lambda r: r[0].update(campaign_id=999), lambda r: r[0].update(layout_version='other')]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(DatasetError):
                load_export(*self.payload(change=mutation))

    def test_unrepresentable_finite_number_is_an_actionable_dataset_error(self):
        for field in ('n_pathloss', 'rssi_1m', 'pos_x'):
            with self.subTest(field=field), self.assertRaises(DatasetError):
                load_export(*self.payload(manifest_change=lambda manifest: manifest['evaluation_context']['anchors'][0].update({field: 10**400})))

    def test_readiness_cannot_be_claimed_by_ready_boolean(self):
        changes = [lambda m: m['evaluation_context'].update(audit_ok=False),
                   lambda m: m['evaluation_context']['sessions'][0].update(finished_at=None),
                   lambda m: m['evaluation_context']['sessions'][0].update(independence_evidence_present=False),
                   lambda m: m['evaluation_context']['sessions'][0].update(obstacles_documented=False),
                   lambda m: m['evaluation_context']['anchors'][0].update(n_pathloss=0),
                   lambda m: m.update(anchor_ids=['wrong','N2','N3']),
                   lambda m: m['evaluation_context'].update(blockers=['source audit pending']),
                   lambda m: m.pop('evaluation_context')]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(DatasetError):
                load_export(*self.payload(manifest_change=change))


if __name__ == '__main__':
    unittest.main()
