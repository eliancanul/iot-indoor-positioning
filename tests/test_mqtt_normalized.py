import sys
import types
import tempfile
import unittest
from pathlib import Path
import database as db

class FakeClient:
    def __init__(self, *args, **kwargs): pass

fake_mqtt = types.ModuleType('paho.mqtt.client')
fake_mqtt.Client = FakeClient
fake_mqtt.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
sys.modules['paho'] = types.ModuleType('paho')
sys.modules['paho.mqtt'] = types.ModuleType('paho.mqtt')
sys.modules['paho.mqtt.client'] = fake_mqtt
from mqtt_manager import MQTTManager

class MQTTNormalizedTest(unittest.TestCase):
    def test_calculated_cycle_is_saved_to_normalized_tables(self):
        db.DB_PATH = str(Path(tempfile.mkdtemp()) / 'test.db')
        db.init_db()
        ok, area_id = db.crear_area('Test', 6, 8, 2, 2)
        self.assertTrue(ok)
        nodes = [
            {'node_id':'N0','topic':'T0','pos_x':0.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N1','topic':'T1','pos_x':4.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N2','topic':'T2','pos_x':0.0,'pos_y':4.0,'rssi_1m':-60.0},
        ]
        campaign_id = db.crear_campana(
            area_id=area_id,
            codigo='campaign-test',
            descripcion='Campaña de prueba',
            condiciones_ambientales='Controladas',
            orden_posiciones=[(0, 0)],
        )
        session_id = db.crear_sesion_captura(
            campaign_id=campaign_id,
            area_id=area_id,
            orientation='north',
            environment_tag='baseline-v1',
            layout_version='layout-v1',
            independence_evidence='Recolocación de prueba',
            obstacle_description='Sin obstáculos',
            node_schema_hash='N0|N1|N2',
        )
        manager = MQTTManager()
        manager.areas_config[area_id] = nodes
        manager.asignar_sesion_captura(area_id, session_id)
        manager.asignar_posicion_captura(area_id, (0.0, 0.0))
        manager.sample_counter[area_id] = 0
        data = {'rssi': {'T0':[-60,-61,-59], 'T1':[-70,-71,-69], 'T2':[-70,-71,-69]}, 'triang':[], 'circulos':[]}
        manager._calcular_posicion(data, area_id, 3)
        conn = db.get_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM dataset').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM collection_sessions').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM fingerprint_samples').fetchone()[0], 1)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM fingerprint_readings').fetchone()[0], 3)
        row = conn.execute('SELECT rssi_median, reading_count, raw_values_json FROM fingerprint_readings WHERE node_id="N0"').fetchone()
        self.assertEqual(row[0], -60.0)
        self.assertEqual(row[1], 3)
        self.assertEqual(row[2], '[-60,-61,-59]')

    def test_capture_position_must_belong_to_the_session_campaign(self):
        db.DB_PATH = str(Path(tempfile.mkdtemp()) / 'position.db')
        db.init_db()
        ok, area_id = db.crear_area('Posición', 4, 2, 0, 0)
        self.assertTrue(ok)
        campaign_id = db.crear_campana(
            area_id=area_id,
            codigo='position-campaign',
            descripcion='Ruta fija',
            condiciones_ambientales='Controladas',
            orden_posiciones=[(0, 0), (1, 0)],
        )
        session_id = db.crear_sesion_captura(
            campaign_id=campaign_id,
            area_id=area_id,
            orientation='north',
            environment_tag='baseline-v1',
            layout_version='layout-v1',
            independence_evidence='Recolocación y horario documentados',
            obstacle_description='Sin obstáculos',
        )

        manager = MQTTManager()
        manager.asignar_sesion_captura(area_id, session_id)
        self.assertIsNone(manager.obtener_posicion_captura(area_id))
        with self.assertRaises(ValueError):
            manager.asignar_posicion_captura(area_id, (2.0, 0.0))

        manager.asignar_posicion_captura(area_id, (1.0, 0.0))
        self.assertEqual(manager.obtener_posicion_captura(area_id), (1.0, 0.0))

        db.cerrar_sesion(session_id)
        with self.assertRaises(ValueError):
            manager.asignar_sesion_captura(area_id, session_id)

    def test_new_capture_requires_an_explicit_capture_position(self):
        db.DB_PATH = str(Path(tempfile.mkdtemp()) / 'position-required.db')
        db.init_db()
        ok, area_id = db.crear_area('Posición requerida', 6, 8, 2, 2)
        self.assertTrue(ok)
        nodes = [
            {'node_id':'N0','topic':'T0','pos_x':0.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N1','topic':'T1','pos_x':4.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N2','topic':'T2','pos_x':0.0,'pos_y':4.0,'rssi_1m':-60.0},
        ]
        campaign_id = db.crear_campana(
            area_id=area_id,
            codigo='position-required-campaign',
            descripcion='Ruta fija',
            condiciones_ambientales='Controladas',
            orden_posiciones=[(0, 0)],
        )
        session_id = db.crear_sesion_captura(
            campaign_id=campaign_id,
            area_id=area_id,
            orientation='north',
            environment_tag='baseline-v1',
            layout_version='layout-v1',
            independence_evidence='Recolocación documentada',
            obstacle_description='Sin obstáculos',
        )
        manager = MQTTManager()
        manager.areas_config[area_id] = nodes
        manager.asignar_sesion_captura(area_id, session_id)
        data = {'rssi': {'T0':[-60,-61,-59], 'T1':[-70,-71,-69], 'T2':[-70,-71,-69]}, 'triang':[], 'circulos':[]}

        manager._calcular_posicion(data, area_id, 3)

        conn = db.get_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM fingerprint_samples').fetchone()[0], 0)
        conn.close()

    def test_new_capture_requires_an_explicit_physical_session(self):
        db.DB_PATH = str(Path(tempfile.mkdtemp()) / 'context-required.db')
        db.init_db()
        ok, area_id = db.crear_area('Contexto', 6, 8, 2, 2)
        self.assertTrue(ok)
        nodes = [
            {'node_id':'N0','topic':'T0','pos_x':0.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N1','topic':'T1','pos_x':4.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N2','topic':'T2','pos_x':0.0,'pos_y':4.0,'rssi_1m':-60.0},
        ]
        manager = MQTTManager()
        manager.areas_config[area_id] = nodes
        data = {'rssi': {'T0':[-60,-61,-59], 'T1':[-70,-71,-69], 'T2':[-70,-71,-69]}, 'triang':[], 'circulos':[]}

        manager._calcular_posicion(data, area_id, 3)

        conn = db.get_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM fingerprint_samples').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM dataset').fetchone()[0], 0)
        conn.close()

    def test_noisy_cycle_is_preserved_as_dirty_in_normalized_capture(self):
        db.DB_PATH = str(Path(tempfile.mkdtemp()) / 'dirty.db')
        db.init_db()
        ok, area_id = db.crear_area('Dirty', 6, 8, 2, 2)
        self.assertTrue(ok)
        nodes = [
            {'node_id':'N0','topic':'T0','pos_x':0.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N1','topic':'T1','pos_x':4.0,'pos_y':0.0,'rssi_1m':-60.0},
            {'node_id':'N2','topic':'T2','pos_x':0.0,'pos_y':4.0,'rssi_1m':-60.0},
        ]
        campaign_id = db.crear_campana(
            area_id=area_id, codigo='dirty-campaign', descripcion='Dirty',
            condiciones_ambientales='Prueba', orden_posiciones=[(0, 0)],
        )
        session_id = db.crear_sesion_captura(
            campaign_id=campaign_id, area_id=area_id, orientation='north',
            environment_tag='baseline-v1', layout_version='layout-v1',
            independence_evidence='Recolocación', obstacle_description='Sin obstáculos',
            node_schema_hash='N0|N1|N2',
        )
        manager = MQTTManager()
        manager.areas_config[area_id] = nodes
        manager.asignar_sesion_captura(area_id, session_id)
        manager.asignar_posicion_captura(area_id, (0.0, 0.0))
        data = {
            'rssi': {
                'T0': [-90, -90, -90, -70, -70, -70],
                'T1': [-70, -70, -70],
                'T2': [-80, -80, -80],
            },
            'triang': [], 'circulos': [],
        }

        manager._calcular_posicion(data, area_id, 3)

        conn = db.get_connection()
        sample = conn.execute(
            'SELECT quality_status, quality_reasons_json FROM fingerprint_samples'
        ).fetchone()
        readings = conn.execute(
            'SELECT COUNT(*) FROM fingerprint_readings'
        ).fetchone()[0]
        legacy = conn.execute('SELECT COUNT(*) FROM dataset').fetchone()[0]
        conn.close()
        self.assertEqual(sample['quality_status'], 'dirty')
        self.assertIn('high_iqr', sample['quality_reasons_json'])
        self.assertEqual(readings, 3)
        self.assertEqual(legacy, 0)

if __name__ == '__main__':
    unittest.main()
