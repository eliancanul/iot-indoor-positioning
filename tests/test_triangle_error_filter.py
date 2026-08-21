import sys
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

mqtt = types.ModuleType('paho.mqtt.client')
mqtt.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
mqtt.Client = object
sys.modules.setdefault('paho', types.ModuleType('paho'))
sys.modules.setdefault('paho.mqtt', types.ModuleType('paho.mqtt'))
sys.modules['paho.mqtt.client'] = mqtt

import database as db
from mqtt_manager import MQTTManager


class TriangleErrorFilterTest(unittest.TestCase):
    def setUp(self):
        self.old_path = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db.DB_PATH = str(Path(self.temp.name) / 'capture.db')
        db.init_db()
        ok, self.area_id = db.crear_area('test', 10, 10, 2, 2)
        self.assertTrue(ok)
        self.nodes = [
            {'node_id': 'N0', 'topic': 'T0', 'pos_x': 0.0, 'pos_y': 0.0, 'rssi_1m': -60.0},
            {'node_id': 'N1', 'topic': 'T1', 'pos_x': 4.0, 'pos_y': 0.0, 'rssi_1m': -60.0},
            {'node_id': 'N2', 'topic': 'T2', 'pos_x': 0.0, 'pos_y': 4.0, 'rssi_1m': -60.0},
        ]
        for node in self.nodes:
            ok, _ = db.crear_esp32(
                node['node_id'], node['topic'], node['pos_x'], node['pos_y'],
                node['rssi_1m'], self.area_id,
            )
            self.assertTrue(ok)
        campaign_id = db.crear_campana(
            area_id=self.area_id,
            codigo='campaign-test',
            descripcion='Campaña de prueba',
            condiciones_ambientales='Controladas',
            orden_posiciones=[(2, 2)],
        )
        self.session_id = db.crear_sesion_captura(
            campaign_id=campaign_id,
            area_id=self.area_id,
            orientation='north',
            environment_tag='baseline-v1',
            layout_version='layout-v1',
            independence_evidence='Recolocación de prueba',
            obstacle_description='Sin obstáculos',
            node_schema_hash='N0|N1|N2',
        )

    def tearDown(self):
        db.DB_PATH = self.old_path
        self.temp.cleanup()

    def test_high_triangle_error_keeps_circle_and_excludes_triangle_estimate(self):
        db.set_config('max_error_triangulos', '2.0')
        manager = MQTTManager()
        manager.areas_config[self.area_id] = self.nodes
        manager.asignar_sesion_captura(self.area_id, self.session_id)
        manager.asignar_posicion_captura(self.area_id, (2.0, 2.0))
        data = {
            'rssi': {'T0': [-60] * 3, 'T1': [-70] * 3, 'T2': [-70] * 3},
            'triang': [],
            'circulos': [],
        }

        with patch('mqtt_manager.triangulos', return_value=(9.0, 9.0)), \
             patch('mqtt_manager.circulos', return_value=(2.0, 2.0)):
            manager._calcular_posicion(data, self.area_id, 3)

        self.assertEqual(data['triang'], [])
        self.assertEqual(data['circulos'], [(2.0, 2.0)])
        self.assertEqual(
            data['latest_estimate'],
            {'method': 'circulos', 'position': (2.0, 2.0)},
        )
        conn = db.get_connection()
        self.assertEqual(
            [tuple(row) for row in conn.execute('SELECT method FROM position_estimates').fetchall()],
            [('circulos',)],
        )
        row = conn.execute('SELECT x_tri, y_tri, x_circ, y_circ FROM dataset').fetchone()
        self.assertEqual(tuple(row), (None, None, 2.0, 2.0))
        diagnostic = conn.execute(
            'SELECT method, reason, residual_m FROM position_estimate_diagnostics'
        ).fetchone()
        conn.close()
        self.assertEqual(diagnostic['method'], 'triangulos')
        self.assertEqual(diagnostic['reason'], 'high_error')
        self.assertAlmostEqual(diagnostic['residual_m'], (7 ** 2 + 7 ** 2) ** 0.5)

    def test_persistence_boundary_also_rejects_high_triangle_error(self):
        result = db.guardar_ciclo_captura(
            area_id=self.area_id, session_id=None, cycle_id='db-guard-1',
            x_real=2.0, y_real=2.0,
            readings=[
                {'node_id': 'N0', 'rssi_values': [-60], 'captured_at': 1.0},
                {'node_id': 'N1', 'rssi_values': [-70], 'captured_at': 1.0},
                {'node_id': 'N2', 'rssi_values': [-70], 'captured_at': 1.0},
            ],
            estimates={'triangulos': (9.0, 9.0), 'circulos': (2.0, 2.0)},
            max_window_skew_s=2.0, max_error_triangulos=2.0,
        )
        self.assertTrue(result['saved'])
        self.assertEqual(result['estimate_count'], 1)
        conn = db.get_connection()
        methods = [row['method'] for row in conn.execute('SELECT method FROM position_estimates')]
        conn.close()
        self.assertEqual(methods, ['circulos'])

    def test_two_methods_are_saved_as_individual_comparisons_when_both_are_valid(self):
        db.set_config('max_error_triangulos', '20.0')
        manager = MQTTManager()
        manager.areas_config[self.area_id] = self.nodes
        manager.asignar_sesion_captura(self.area_id, self.session_id)
        manager.asignar_posicion_captura(self.area_id, (2.0, 2.0))
        data = {
            'rssi': {'T0': [-60] * 3, 'T1': [-70] * 3, 'T2': [-70] * 3},
            'triang': [],
            'circulos': [],
        }

        with patch('mqtt_manager.triangulos', return_value=(1.0, 1.0)), \
             patch('mqtt_manager.circulos', return_value=(3.0, 2.0)):
            manager._calcular_posicion(data, self.area_id, 3)

        conn = db.get_connection()
        rows = conn.execute(
            'SELECT method, x_estimated, y_estimated, error_m '
            'FROM position_estimates ORDER BY method'
        ).fetchall()
        conn.close()
        self.assertEqual([row['method'] for row in rows], ['circulos', 'triangulos'])
        self.assertAlmostEqual(rows[0]['error_m'], 1.0)
        self.assertAlmostEqual(rows[1]['error_m'], 2 ** 0.5)


if __name__ == '__main__':
    unittest.main()
